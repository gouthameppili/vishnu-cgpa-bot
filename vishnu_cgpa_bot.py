import logging
import re
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
import os
from typing import Dict, Optional
import time

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set. Please set it in .env file or as an environment variable.")

RESULTS_URL = "https://vishnu.edu.in/Results.php"
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3
RATE_LIMIT_DELAY = 1  # seconds between requests

class CGPAExtractor:
    """Handles web scraping and CGPA extraction from Vishnu Institute website."""

    def __init__(self):
        self.last_request_time = 0
        
    async def _create_session(self) -> aiohttp.ClientSession:
        """Create an aiohttp session with proper headers."""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0'
        }
        
        connector = aiohttp.TCPConnector(
            limit=10,
            limit_per_host=5,
            ttl_dns_cache=300,
            use_dns_cache=True,
        )
        
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        
        return aiohttp.ClientSession(
            headers=headers,
            connector=connector,
            timeout=timeout
        )

    def _validate_roll_number(self, roll_number: str) -> Dict[str, any]:
        """Validate roll number format."""
        if not roll_number or not roll_number.strip():
            return {
                'valid': False,
                'message': 'Please provide a valid roll number.'
            }
        
        # Clean roll number
        roll_number = roll_number.strip().upper()
        
        # Check basic format - should be alphanumeric
        if not re.match(r'^[A-Z0-9]+$', roll_number):
            return {
                'valid': False,
                'message': 'Roll number should contain only letters and numbers.'
            }
        
        # Check length (typically 10-12 characters for most institutions)
        if len(roll_number) < 8 or len(roll_number) > 15:
            return {
                'valid': False,
                'message': 'Roll number length seems invalid. Please check and try again.'
            }
        
        return {
            'valid': True,
            'roll_number': roll_number
        }

    async def _rate_limit(self):
        """Implement rate limiting to be respectful to the server."""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        
        if time_since_last_request < RATE_LIMIT_DELAY:
            await asyncio.sleep(RATE_LIMIT_DELAY - time_since_last_request)
        
        self.last_request_time = time.time()

    async def get_cgpa(self, roll_number: str) -> Dict[str, any]:
        """
        Retrieve CGPA for a given roll number.

        Args:
            roll_number (str): Student roll number

        Returns:
            dict: Result containing success status, CGPA, and message
        """
        # Validate roll number
        validation = self._validate_roll_number(roll_number)
        if not validation['valid']:
            return {
                'success': False,
                'message': validation['message']
            }
        
        roll_number = validation['roll_number']
        
        # Rate limiting
        await self._rate_limit()
        
        for attempt in range(MAX_RETRIES):
            try:
                logger.info(f"Attempt {attempt + 1}/{MAX_RETRIES} for roll number: {roll_number}")
                
                async with await self._create_session() as session:
                    # Try POST request first
                    result = await self._try_post_request(session, roll_number)
                    if result['success']:
                        return result
                    
                    # If POST fails, try GET request
                    result = await self._try_get_request(session, roll_number)
                    if result['success']:
                        return result
                
                # If this attempt failed and we have more attempts, wait before retrying
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    
            except aiohttp.ClientError as e:
                logger.error(f"Network error on attempt {attempt + 1}: {e}")
                if attempt == MAX_RETRIES - 1:
                    return {
                        'success': False,
                        'message': 'Network error occurred. Please check your internet connection and try again.'
                    }
            except asyncio.TimeoutError:
                logger.error(f"Timeout error on attempt {attempt + 1}")
                if attempt == MAX_RETRIES - 1:
                    return {
                        'success': False,
                        'message': 'Request timed out. The website might be slow. Please try again later.'
                    }
            except Exception as e:
                logger.error(f"Unexpected error on attempt {attempt + 1}: {e}")
                if attempt == MAX_RETRIES - 1:
                    return {
                        'success': False,
                        'message': 'An unexpected error occurred. Please try again later.'
                    }
        
        return {
            'success': False,
            'message': 'Unable to retrieve results after multiple attempts. The website might be temporarily unavailable.'
        }

    async def _try_post_request(self, session: aiohttp.ClientSession, roll_number: str) -> Dict[str, any]:
        """Try submitting roll number via POST request."""
        try:
            # First get the page to analyze form structure
            async with session.get(RESULTS_URL) as response:
                if response.status != 200:
                    return {'success': False, 'message': f'Website returned status {response.status}'}
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                # Look for form
                form = soup.find('form')
                if not form:
                    return {'success': False, 'message': 'Form not found'}
                
                # Find input field for roll number
                input_field_name = self._find_roll_number_field(soup)
                if not input_field_name:
                    return {'success': False, 'message': 'Roll number input field not found'}
                
                # Prepare form data
                form_data = {input_field_name: roll_number}
                
                # Look for submit button
                submit_button = soup.find('input', {'type': 'submit'})
                if submit_button and submit_button.get('name'):
                    form_data[submit_button.get('name')] = submit_button.get('value', 'Submit')
                
                # Find any hidden fields
                hidden_fields = soup.find_all('input', {'type': 'hidden'})
                for field in hidden_fields:
                    name = field.get('name')
                    value = field.get('value', '')
                    if name:
                        form_data[name] = value
                
                # Get form action URL
                action = form.get('action', RESULTS_URL)
                if action.startswith('/'):
                    action = 'https://vishnu.edu.in' + action
                elif not action.startswith('http'):
                    action = RESULTS_URL
                
                logger.info(f"Submitting POST to {action}")
                
                # Submit the form
                async with session.post(action, data=form_data) as post_response:
                    if post_response.status == 200:
                        result_html = await post_response.text()
                        return self._extract_cgpa_from_html(result_html, roll_number)
                    else:
                        return {'success': False, 'message': f'POST request failed with status {post_response.status}'}
                        
        except Exception as e:
            logger.error(f"POST request failed: {e}")
            return {'success': False, 'message': 'POST request failed'}

    async def _try_get_request(self, session: aiohttp.ClientSession, roll_number: str) -> Dict[str, any]:
        """Try submitting roll number via GET request."""
        try:
            # Common parameter names for roll number
            possible_params = ['rollno', 'roll_no', 'regdno', 'regno', 'student_id', 'rollnumber', 'rno']
            
            for param in possible_params:
                url = f"{RESULTS_URL}?{param}={roll_number}"
                logger.info(f"Trying GET request: {url}")
                
                async with session.get(url) as response:
                    if response.status == 200:
                        html = await response.text()
                        result = self._extract_cgpa_from_html(html, roll_number)
                        if result['success']:
                            return result
            
            return {'success': False, 'message': 'GET request attempts failed'}
            
        except Exception as e:
            logger.error(f"GET request failed: {e}")
            return {'success': False, 'message': 'GET request failed'}

    def _find_roll_number_field(self, soup: BeautifulSoup) -> Optional[str]:
        """Find the input field name for roll number."""
        # Common field names for roll number input
        possible_names = ['rollno', 'roll_no', 'regdno', 'regno', 'student_id', 'rollnumber', 'rno', 'regdno', 'htno']
        
        for name in possible_names:
            field = soup.find('input', {'name': name})
            if field:
                return name
        
        # Look for input fields with roll-related id or class
        roll_inputs = soup.find_all('input', attrs={
            'id': re.compile(r'roll|reg|student', re.I),
            'class': re.compile(r'roll|reg|student', re.I)
        })
        
        for input_field in roll_inputs:
            name = input_field.get('name')
            if name:
                return name
        
        # Fallback: find any text input field
        text_input = soup.find('input', {'type': 'text'})
        if text_input and text_input.get('name'):
            return text_input.get('name')
        
        return None

    def _extract_cgpa_from_html(self, html: str, roll_number: str) -> Dict[str, any]:
        """Extract CGPA from HTML response."""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            text_content = soup.get_text().lower()
            
            # Check for error indicators
            error_indicators = [
                'not found', 'invalid', 'error', 'no results', 'no record',
                'not available', 'does not exist', 'incorrect', 'wrong'
            ]
            
            for indicator in error_indicators:
                if indicator in text_content:
                    return {
                        'success': False,
                        'message': f'Roll number {roll_number} not found in the system. Please verify your roll number.'
                    }
            
            # Multiple strategies to find CGPA
            cgpa = self._find_cgpa_in_text(text_content)
            
            if not cgpa:
                cgpa = self._find_cgpa_in_elements(soup)
            
            if not cgpa:
                cgpa = self._find_cgpa_in_tables(soup)
            
            if cgpa:
                # Validate CGPA value
                try:
                    cgpa_float = float(cgpa)
                    if 0 <= cgpa_float <= 10:
                        return {
                            'success': True,
                            'cgpa': f"{cgpa_float:.2f}",
                            'message': f'CGPA for roll number {roll_number}: {cgpa_float:.2f}'
                        }
                    else:
                        logger.warning(f"CGPA value {cgpa_float} seems invalid")
                except ValueError:
                    logger.warning(f"Could not convert CGPA '{cgpa}' to float")
            
            # Log HTML for debugging (first 500 characters)
            logger.info(f"Could not extract CGPA. HTML preview: {html[:500]}")
            return {
                'success': False,
                'message': f'CGPA information not found for roll number {roll_number}. Results might not be published yet or the page format has changed.'
            }
            
        except Exception as e:
            logger.error(f"Error extracting CGPA: {e}")
            return {
                'success': False,
                'message': 'Error processing results page. Please try again later.'
            }

    def _find_cgpa_in_text(self, text_content: str) -> Optional[str]:
        """Find CGPA using regex patterns in text content."""
        cgpa_patterns = [
            r'cgpa\s*:?\s*(\d+\.?\d*)',
            r'c\.?g\.?p\.?a\.?\s*:?\s*(\d+\.?\d*)',
            r'cumulative.*?grade.*?point.*?average\s*:?\s*(\d+\.?\d*)',
            r'overall.*?gpa\s*:?\s*(\d+\.?\d*)',
            r'final.*?cgpa\s*:?\s*(\d+\.?\d*)',
            r'total.*?cgpa\s*:?\s*(\d+\.?\d*)',
            r'grade.*?point.*?average\s*:?\s*(\d+\.?\d*)',
        ]
        
        for pattern in cgpa_patterns:
            match = re.search(pattern, text_content, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None

    def _find_cgpa_in_elements(self, soup: BeautifulSoup) -> Optional[str]:
        """Find CGPA in specific HTML elements."""
        # Look for elements with CGPA-related classes or ids
        cgpa_elements = soup.find_all(
            ['span', 'div', 'td', 'p', 'strong', 'b'],
            attrs={
                'class': re.compile(r'cgpa|gpa|grade', re.I),
                'id': re.compile(r'cgpa|gpa|grade', re.I)
            }
        )
        
        for element in cgpa_elements:
            text = element.get_text().strip()
            number_match = re.search(r'(\d+\.?\d*)', text)
            if number_match:
                potential_cgpa = float(number_match.group(1))
                if 0 <= potential_cgpa <= 10:
                    return str(potential_cgpa)
        
        return None

    def _find_cgpa_in_tables(self, soup: BeautifulSoup) -> Optional[str]:
        """Find CGPA in table structures."""
        tables = soup.find_all('table')
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all(['td', 'th'])
                for i, cell in enumerate(cells):
                    cell_text = cell.get_text().lower()
                    
                    # Check if cell contains CGPA-related keywords
                    if any(keyword in cell_text for keyword in ['cgpa', 'gpa', 'grade point', 'cumulative']):
                        # Look for number in next cell
                        if i + 1 < len(cells):
                            next_cell = cells[i + 1].get_text().strip()
                            number_match = re.search(r'(\d+\.?\d*)', next_cell)
                            if number_match:
                                potential_cgpa = float(number_match.group(1))
                                if 0 <= potential_cgpa <= 10:
                                    return str(potential_cgpa)
                        
                        # Also check current cell for CGPA value
                        number_match = re.search(r'(\d+\.?\d*)', cell_text)
                        if number_match:
                            potential_cgpa = float(number_match.group(1))
                            if 0 <= potential_cgpa <= 10:
                                return str(potential_cgpa)
        
        return None

# Initialize CGPA extractor
cgpa_extractor = CGPAExtractor()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    welcome_message = """
🎓 **Welcome to Vishnu CGPA Bot!** 🎓

I can help you retrieve your CGPA from Vishnu Institute of Technology.

📝 **How to use:**
Simply send me your roll number and I'll fetch your CGPA for you.

**Example:**
Just type: `21A91A0501` or `20A91A0234`

⚡ **Features:**
• Fast and reliable CGPA retrieval
• Automatic retry on failures  
• Input validation
• Rate limiting for server protection

🔍 Ready to check your CGPA? Send me your roll number now!

**Note:** Make sure your roll number is correct and results are published.
    """

    await update.message.reply_text(
        welcome_message,
        parse_mode='Markdown'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command."""
    help_message = """
🆘 **Help - Vishnu CGPA Bot**

**Commands:**
• `/start` - Start the bot and see welcome message
• `/help` - Show this help message

**Usage:**
1. Simply send your roll number as a text message
2. Wait for the bot to fetch your CGPA

**Examples:**
• `21A91A0501`
• `20A91A0234`
• `19A91A1234`

**Troubleshooting:**
• ✅ Make sure your roll number is correct
• ✅ Check if results are published for your batch
• ✅ Try again if the website is temporarily unavailable
• ✅ Roll number should contain only letters and numbers

**Features:**
• 🚀 Fast processing with multiple attempts
• 🔒 Input validation for security
• ⚡ Automatic retry mechanism
• 🛡️ Rate limiting to protect the server

**Note:** This bot fetches data from the official Vishnu Institute website.
    """

    await update.message.reply_text(
        help_message,
        parse_mode='Markdown'
    )

async def handle_roll_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle roll number input from user."""
    user_input = update.message.text.strip()

    # Log user request
    user_id = update.effective_user.id
    username = update.effective_user.username or "N/A"
    logger.info(f"CGPA request from user {user_id} (@{username}): {user_input}")

    # Quick validation
    if not user_input:
        await update.message.reply_text(
            "❌ Please provide a valid roll number.\n\n"
            "**Example:** `21A91A0501`",
            parse_mode='Markdown'
        )
        return

    # Check for obvious non-roll-number inputs
    if len(user_input.split()) > 1:  # Multiple words
        await update.message.reply_text(
            "❌ Please provide only your roll number.\n\n"
            "**Example:** `21A91A0501`",
            parse_mode='Markdown'
        )
        return

    # Send processing message
    processing_message = await update.message.reply_text(
        f"🔍 **Processing roll number:** `{user_input}`\n"
        "⏳ Please wait while I fetch your CGPA...\n"
        "This may take a few seconds.",
        parse_mode='Markdown'
    )

    try:
        # Fetch CGPA using async method
        result = await cgpa_extractor.get_cgpa(user_input)

        if result['success']:
            # Success message with more details
            success_message = f"""
✅ **Results Found Successfully!**

🎓 **Roll Number:** `{user_input}`
📊 **CGPA:** `{result['cgpa']}`

🎉 **Congratulations!** Keep up the excellent work!

⏰ *Results fetched at {time.strftime('%Y-%m-%d %H:%M:%S')}*
            """
            await processing_message.edit_text(
                success_message.strip(),
                parse_mode='Markdown'
            )
            
            # Log successful retrieval
            logger.info(f"Successfully retrieved CGPA {result['cgpa']} for roll number {user_input}")
            
        else:
            # Error message with helpful suggestions
            error_message = f"""
❌ **Unable to retrieve CGPA**

🔢 **Roll Number:** `{user_input}`
⚠️ **Issue:** {result['message']}

**Please verify:**
• ✅ Roll number is spelled correctly
• ✅ Results are published for your batch
• ✅ Website is accessible
• ✅ Roll number format is correct (letters and numbers only)

💡 **Tip:** Try again in a few minutes if the website is busy.
            """
            await processing_message.edit_text(
                error_message.strip(),
                parse_mode='Markdown'
            )
            
            # Log failed attempt
            logger.warning(f"Failed to retrieve CGPA for roll number {user_input}: {result['message']}")

    except Exception as e:
        logger.error(f"Error processing roll number {user_input}: {e}")
        await processing_message.edit_text(
            f"❌ **Unexpected error occurred**\n\n"
            f"**Roll number:** `{user_input}`\n"
            f"**Error:** System error while processing your request.\n\n"
            f"Please try again later. If the issue persists, the website might be temporarily unavailable.",
            parse_mode='Markdown'
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors."""
    logger.error(f"Exception while handling an update: {context.error}")

    try:
        if update and update.message:
            await update.message.reply_text(
                "❌ **An unexpected error occurred**\n\n"
                "Please try again later. If the problem persists, the website might be temporarily unavailable.\n\n"
                "Use /help for more information."
            )
    except Exception as e:
        # If we can't even send an error message, just log it
        logger.error(f"Could not send error message to user: {e}")

def main() -> None:
    """Start the bot."""
    # Validate environment
    if not BOT_TOKEN:
        print("❌ Error: BOT_TOKEN not found in environment variables")
        print("Please create a .env file with BOT_TOKEN=your_bot_token")
        return
    
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_roll_number))

    # Add error handler
    application.add_error_handler(error_handler)

    # Start the bot
    print("🤖 Vishnu CGPA Bot is starting...")
    print(f"📡 Bot token: {BOT_TOKEN[:10]}...")
    print("🌐 Target website: " + RESULTS_URL)
    print("Press Ctrl+C to stop the bot")

    try:
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True  # Clear pending updates on startup
        )
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"❌ Error starting bot: {e}")
        logger.error(f"Bot startup error: {e}")

if __name__ == '__main__':
    main()