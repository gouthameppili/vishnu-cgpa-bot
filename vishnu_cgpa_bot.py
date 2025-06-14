#!/usr/bin/env python3
"""
Vishnu CGPA Telegram Bot with PDF Marksheet Generation
A Telegram bot that retrieves student CGPA from Vishnu Institute website and generates PDF marksheets.

Requirements:
pip install python-telegram-bot requests beautifulsoup4 lxml weasyprint

System Dependencies (Linux/Ubuntu):
sudo apt-get install -y libffi-dev libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libxml2-dev libxslt1-dev

Usage:
python vishnu_cgpa_bot.py
"""

import logging
import re
import asyncio
import os
import tempfile
from typing import Optional
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = "7331481570:AAEWqwmCYL-mLUlcKXySfmY0p_728D9gZxA"
RESULTS_URL = "https://vishnu.edu.in/Results.php"

class CGPAExtractor:
    """Handles web scraping and CGPA extraction from Vishnu Institute website."""
    
    def __init__(self):
        self.session = requests.Session()
        # Add headers to mimic a real browser
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
    
    def get_cgpa(self, roll_number: str) -> dict:
        """
        Retrieve CGPA for a given roll number.
        
        Args:
            roll_number (str): Student roll number
            
        Returns:
            dict: Result containing success status, CGPA, HTML content, and message
        """
        try:
            # Clean roll number (remove spaces, convert to uppercase)
            roll_number = roll_number.strip().upper()
            
            if not roll_number:
                return {
                    'success': False,
                    'message': 'Please provide a valid roll number.'
                }
            
            # First, get the results page to check for any form parameters
            logger.info(f"Fetching results page for roll number: {roll_number}")
            
            # Try different common approaches for submitting roll number
            result = self._try_post_request(roll_number)
            if result['success']:
                return result
                
            result = self._try_get_request(roll_number)
            if result['success']:
                return result
            
            return {
                'success': False,
                'message': 'Unable to retrieve results. The website might be temporarily unavailable or the roll number format might be incorrect.'
            }
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error: {e}")
            return {
                'success': False,
                'message': 'Network error occurred. Please try again later.'
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return {
                'success': False,
                'message': 'An unexpected error occurred. Please try again later.'
            }
    
    def _try_post_request(self, roll_number: str) -> dict:
        """Try submitting roll number via POST request."""
        try:
            # First get the page to find form structure
            response = self.session.get(RESULTS_URL, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Look for form and input fields
            form = soup.find('form')
            if not form:
                return {'success': False, 'message': 'Form not found'}
            
            # Common field names for roll number input
            possible_field_names = ['rollno', 'roll_no', 'regdno', 'regno', 'student_id', 'rollnumber']
            
            input_field = None
            field_name = None
            
            for name in possible_field_names:
                input_field = soup.find('input', {'name': name})
                if input_field:
                    field_name = name
                    break
            
            if not input_field:
                # Try to find any text input field
                input_field = soup.find('input', {'type': 'text'})
                if input_field and input_field.get('name'):
                    field_name = input_field.get('name')
            
            if not field_name:
                return {'success': False, 'message': 'Roll number input field not found'}
            
            # Prepare form data
            form_data = {field_name: roll_number}
            
            # Look for submit button
            submit_button = soup.find('input', {'type': 'submit'})
            if submit_button and submit_button.get('name'):
                form_data[submit_button.get('name')] = submit_button.get('value', 'Submit')
            
            # Get form action URL
            action = form.get('action', RESULTS_URL)
            if action.startswith('/'):
                action = 'https://vishnu.edu.in' + action
            elif not action.startswith('http'):
                action = RESULTS_URL
            
            logger.info(f"Submitting POST request to {action} with data: {form_data}")
            
            # Submit the form
            response = self.session.post(action, data=form_data, timeout=15)
            response.raise_for_status()
            
            return self._extract_cgpa_from_html(response.text, roll_number)
            
        except Exception as e:
            logger.error(f"POST request failed: {e}")
            return {'success': False, 'message': 'POST request failed'}
    
    def _try_get_request(self, roll_number: str) -> dict:
        """Try submitting roll number via GET request."""
        try:
            # Common parameter names
            possible_params = ['rollno', 'roll_no', 'regdno', 'regno', 'student_id']
            
            for param in possible_params:
                url = f"{RESULTS_URL}?{param}={roll_number}"
                logger.info(f"Trying GET request: {url}")
                
                response = self.session.get(url, timeout=10)
                response.raise_for_status()
                
                result = self._extract_cgpa_from_html(response.text, roll_number)
                if result['success']:
                    return result
            
            return {'success': False, 'message': 'GET request failed'}
            
        except Exception as e:
            logger.error(f"GET request failed: {e}")
            return {'success': False, 'message': 'GET request failed'}
    
    def _extract_cgpa_from_html(self, html: str, roll_number: str) -> dict:
        """Extract CGPA from HTML response."""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Check if roll number was not found
            error_indicators = ['not found', 'invalid', 'error', 'no results', 'no record']
            text_content = soup.get_text().lower()
            
            for indicator in error_indicators:
                if indicator in text_content:
                    return {
                        'success': False,
                        'message': f'Roll number {roll_number} not found or results unavailable.'
                    }
            
            # Try multiple strategies to find CGPA
            cgpa = None
            
            # Strategy 1: Look for common CGPA patterns in text
            cgpa_patterns = [
                r'cgpa\s*:?\s*(\d+\.?\d*)',
                r'c\.?g\.?p\.?a\.?\s*:?\s*(\d+\.?\d*)',
                r'cumulative.*?grade.*?point.*?average\s*:?\s*(\d+\.?\d*)',
                r'overall.*?gpa\s*:?\s*(\d+\.?\d*)',
                r'final.*?cgpa\s*:?\s*(\d+\.?\d*)',
                r'total.*?cgpa\s*:?\s*(\d+\.?\d*)',
            ]
            
            for pattern in cgpa_patterns:
                match = re.search(pattern, text_content, re.IGNORECASE)
                if match:
                    cgpa = match.group(1)
                    break
            
            # Strategy 2: Look in specific HTML elements
            if not cgpa:
                # Look for spans/divs with CGPA-related classes or ids
                cgpa_elements = soup.find_all(['span', 'div', 'td', 'p'], 
                                            attrs={'class': re.compile(r'cgpa|gpa|grade', re.I)})
                
                for element in cgpa_elements:
                    text = element.get_text().strip()
                    # Look for number patterns in CGPA elements
                    number_match = re.search(r'(\d+\.?\d*)', text)
                    if number_match:
                        potential_cgpa = float(number_match.group(1))
                        # CGPA is typically between 0 and 10
                        if 0 <= potential_cgpa <= 10:
                            cgpa = str(potential_cgpa)
                            break
            
            # Strategy 3: Look in table cells
            if not cgpa:
                tables = soup.find_all('table')
                for table in tables:
                    rows = table.find_all('tr')
                    for row in rows:
                        cells = row.find_all(['td', 'th'])
                        for i, cell in enumerate(cells):
                            cell_text = cell.get_text().lower()
                            if any(keyword in cell_text for keyword in ['cgpa', 'gpa', 'grade point']):
                                # Look for number in next cell or same cell
                                if i + 1 < len(cells):
                                    next_cell = cells[i + 1].get_text().strip()
                                    number_match = re.search(r'(\d+\.?\d*)', next_cell)
                                    if number_match:
                                        potential_cgpa = float(number_match.group(1))
                                        if 0 <= potential_cgpa <= 10:
                                            cgpa = str(potential_cgpa)
                                            break
                            
                            # Also check current cell for CGPA value
                            if 'cgpa' in cell_text:
                                number_match = re.search(r'(\d+\.?\d*)', cell_text)
                                if number_match:
                                    potential_cgpa = float(number_match.group(1))
                                    if 0 <= potential_cgpa <= 10:
                                        cgpa = str(potential_cgpa)
                                        break
                        if cgpa:
                            break
                    if cgpa:
                        break
            
            if cgpa:
                return {
                    'success': True,
                    'cgpa': cgpa,
                    'html_content': html,  # Include HTML content for PDF generation
                    'message': f'CGPA for roll number {roll_number}: {cgpa}'
                }
            else:
                # Log the HTML for debugging (first 1000 characters)
                logger.info(f"Could not extract CGPA. HTML preview: {html[:1000]}")
                return {
                    'success': False,
                    'message': f'CGPA information not found for roll number {roll_number}. The results page might have a different format than expected.'
                }
                
        except Exception as e:
            logger.error(f"Error extracting CGPA: {e}")
            return {
                'success': False,
                'message': 'Error processing results page.'
            }

def extract_marksheet_content(soup: BeautifulSoup, roll_number: str) -> Optional[str]:
    """
    Extract and clean marksheet content from BeautifulSoup object.
    
    This function makes assumptions about the HTML structure of vishnu.edu.in/Results.php
    """
    try:
        # Remove scripts, styles, and other non-content elements
        for element in soup(['script', 'style', 'nav', 'header', 'footer']):
            element.decompose()
        
        # Strategy 1: Look for common marksheet container patterns
        marksheet_containers = [
            soup.find('div', {'id': re.compile(r'result|marksheet|student', re.I)}),
            soup.find('div', {'class': re.compile(r'result|marksheet|student', re.I)}),
            soup.find('table', {'class': re.compile(r'result|marksheet|student', re.I)}),
            soup.find('main'),
            soup.find('div', {'class': 'container'}),
        ]
        
        marksheet_content = None
        for container in marksheet_containers:
            if container:
                marksheet_content = container
                break
        
        # Strategy 2: If no specific container found, look for the main table
        if not marksheet_content:
            tables = soup.find_all('table')
            if tables:
                # Assume the largest table contains the marksheet
                marksheet_content = max(tables, key=lambda t: len(t.get_text()))
        
        # Strategy 3: Fallback to body content
        if not marksheet_content:
            marksheet_content = soup.find('body')
        
        if not marksheet_content:
            return None
        
        # Clean up the content further
        # Remove navigation, breadcrumbs, etc.
        for element in marksheet_content.find_all(['nav', 'ul'], {'class': re.compile(r'nav|menu|breadcrumb', re.I)}):
            element.decompose()
        
        # Create a complete HTML document
        html_template = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Marksheet - {roll_number}</title>
        </head>
        <body>
            <div class="header">
                <h1>VISHNU INSTITUTE OF TECHNOLOGY</h1>
                <h2>Student Marksheet</h2>
            </div>
            <div class="student-info">
                <strong>Roll Number: {roll_number}</strong>
            </div>
            {marksheet_content}
        </body>
        </html>
        """
        
        return html_template
        
    except Exception as e:
        logger.error(f"Error extracting marksheet content: {e}")
        return None

async def generate_marksheet_pdf(roll_number: str, html_content: str) -> Optional[str]:
    """
    Generate PDF from marksheet HTML content.
    
    Args:
        roll_number (str): Student roll number
        html_content (str): HTML content from results page
        
    Returns:
        Optional[str]: Path to generated PDF file, or None if failed
    """
    try:
        # Import WeasyPrint
        try:
            from weasyprint import HTML, CSS
        except ImportError:
            logger.error("WeasyPrint not installed. Please install it: pip install weasyprint")
            return None
        
        # Parse HTML content
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Clean and extract marksheet content
        marksheet_html = extract_marksheet_content(soup, roll_number)
        
        if not marksheet_html:
            logger.error("Could not extract marksheet content from HTML")
            return None
        
        # Create temporary file for PDF
        temp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
        temp_pdf.close()
        
        # Basic CSS for PDF styling
        css_content = """
        @page {
            size: A4;
            margin: 1cm;
        }
        body {
            font-family: Arial, sans-serif;
            font-size: 12px;
            line-height: 1.4;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 10px;
        }
        th, td {
            border: 1px solid #ddd;
            padding: 8px;
            text-align: left;
        }
        th {
            background-color: #f2f2f2;
            font-weight: bold;
        }
        .header {
            text-align: center;
            margin-bottom: 20px;
        }
        .student-info {
            margin-bottom: 15px;
        }
        """
        
        # Generate PDF
        HTML(string=marksheet_html).write_pdf(
            temp_pdf.name,
            stylesheets=[CSS(string=css_content)]
        )
        
        return temp_pdf.name
        
    except Exception as e:
        logger.error(f"Error generating PDF: {e}")
        return None

# Initialize CGPA extractor
cgpa_extractor = CGPAExtractor()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    welcome_message = """
🎓 **Welcome to Vishnu CGPA Bot!** 🎓

I can help you retrieve your CGPA from Vishnu Institute of Technology and generate PDF marksheets.

📝 **How to use:**
Simply send me your roll number and I'll fetch your CGPA for you.

**Example:** 
Just type: `21A91A0501` or `20A91A0234`

📄 **New Feature:** After getting your CGPA, I can also generate and send you a complete PDF marksheet!

⚡ **Quick and Easy!**
No need for any commands - just send your roll number directly.

🔍 Ready to check your CGPA? Send me your roll number now!
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
3. Choose whether you want a PDF marksheet
4. Receive your results instantly!

**Examples:**
• `21A91A0501`
• `20A91A0234`
• `19A91A1234`

**PDF Feature:**
After receiving your CGPA results, the bot will ask if you want a PDF marksheet. Reply with:
• **Yes** or **Y** - to generate and receive PDF
• **No** or **N** - to skip PDF generation

**Troubleshooting:**
• Make sure your roll number is correct
• Check if results are published for your batch
• Try again if the website is temporarily unavailable

**Note:** This bot fetches data from the official Vishnu Institute website.
    """
    
    await update.message.reply_text(
        help_message,
        parse_mode='Markdown'
    )

async def handle_roll_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle roll number input from user."""
    user_input = update.message.text.strip()
    
    # Clear any previous PDF confirmation state
    context.user_data.pop('awaiting_pdf_confirmation', None)
    
    # Basic validation for roll number format
    if not user_input:
        await update.message.reply_text(
            "❌ Please provide a valid roll number.\n\n"
            "Example: `21A91A0501`",
            parse_mode='Markdown'
        )
        return
    
    # Check if input looks like a roll number (contains alphanumeric characters)
    if not re.match(r'^[A-Za-z0-9]+$', user_input):
        await update.message.reply_text(
            "❌ Invalid roll number format. Please provide a valid roll number.\n\n"
            "Example: `21A91A0501`",
            parse_mode='Markdown'
        )
        return
    
    # Send processing message
    processing_message = await update.message.reply_text(
        f"🔍 **Processing roll number:** `{user_input}`\n"
        "⏳ Please wait while I fetch your CGPA...",
        parse_mode='Markdown'
    )
    
    try:
        # Fetch CGPA
        result = cgpa_extractor.get_cgpa(user_input)
        
        if result['success']:
            # Success message
            success_message = f"""
✅ **Results Found!**

🎓 **Roll Number:** `{user_input}`
📊 **CGPA:** `{result['cgpa']}`

🎉 Great job! Keep up the excellent work!
            """
            await processing_message.edit_text(
                success_message.strip(),
                parse_mode='Markdown'
            )
            
            # Ask for PDF confirmation
            pdf_question = """
📄 **Would you like to receive your complete marksheet as a PDF file?**

Reply with:
• **Yes** or **Y** - to generate and receive PDF
• **No** or **N** - to skip PDF generation
            """
            
            await update.message.reply_text(
                pdf_question.strip(),
                parse_mode='Markdown'
            )
            
            # Store data for PDF generation
            context.user_data['awaiting_pdf_confirmation'] = True
            context.user_data['roll_number'] = user_input
            context.user_data['html_content'] = result.get('html_content', '')
            
        else:
            # Error message
            error_message = f"""
❌ **Unable to retrieve CGPA**

🔢 **Roll Number:** `{user_input}`
⚠️ **Issue:** {result['message']}

**Please check:**
• Roll number is correct
• Results are published for your batch
• Website is accessible

Try again with the correct roll number or try later.
            """
            await processing_message.edit_text(
                error_message.strip(),
                parse_mode='Markdown'
            )
            
    except Exception as e:
        logger.error(f"Error processing roll number {user_input}: {e}")
        await processing_message.edit_text(
            f"❌ **Error occurred while processing your request**\n\n"
            f"Roll number: `{user_input}`\n"
            f"Please try again later or contact support if the issue persists.",
            parse_mode='Markdown'
        )

async def handle_pdf_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle PDF confirmation from user."""
    
    # Check if we're waiting for PDF confirmation
    if not context.user_data.get('awaiting_pdf_confirmation', False):
        return  # Ignore if not waiting for confirmation
    
    # Reset the confirmation flag immediately
    context.user_data.pop('awaiting_pdf_confirmation', None)
    
    user_response = update.message.text.strip().lower()
    
    if user_response in ['yes', 'y']:
        # User wants PDF
        roll_number = context.user_data.get('roll_number', '')
        html_content = context.user_data.get('html_content', '')
        
        if not roll_number or not html_content:
            await update.message.reply_text(
                "❌ **Error:** Missing data for PDF generation. Please try again with your roll number.",
                parse_mode='Markdown'
            )
            # Clean up user data
            context.user_data.pop('roll_number', None)
            context.user_data.pop('html_content', None)
            return
        
        # Send processing message
        processing_msg = await update.message.reply_text(
            "📄 **Generating your marksheet PDF...**\n⏳ This may take a few moments.",
            parse_mode='Markdown'
        )
        
        try:
            # Generate PDF
            pdf_path = await generate_marksheet_pdf(roll_number, html_content)
            
            if pdf_path and os.path.exists(pdf_path):
                # Send PDF file
                with open(pdf_path, 'rb') as pdf_file:
                    await update.message.reply_document(
                        document=pdf_file,
                        filename=f"marksheet_{roll_number}.pdf",
                        caption=f"📄 **Marksheet for Roll Number:** `{roll_number}`",
                        parse_mode='Markdown'
                    )
                
                # Update processing message
                await processing_msg.edit_text(
                    "✅ **PDF generated and sent successfully!**",
                    parse_mode='Markdown'
                )
                
                # Clean up temporary file
                try:
                    os.remove(pdf_path)
                except Exception as e:
                    logger.error(f"Error removing temporary PDF file: {e}")
            else:
                await processing_msg.edit_text(
                    "❌ **Failed to generate PDF**\n\nThe marksheet data might not be in the expected format.",
                    parse_mode='Markdown'
                )
        
        except Exception as e:
            logger.error(f"Error generating PDF for {roll_number}: {e}")
            await processing_msg.edit_text(
                "❌ **Error generating PDF**\n\nPlease try again later or contact support if the issue persists.",
                parse_mode='Markdown'
            )
        
        # Clean up user data
        context.user_data.pop('roll_number', None)
        context.user_data.pop('html_content', None)
        
    elif user_response in ['no', 'n']:
        # User doesn't want PDF
        await update.message.reply_text(
            "👍 **Okay, no PDF will be generated.**\n\nYou can request your CGPA again anytime by sending your roll number.",
            parse_mode='Markdown'
        )
        
        # Clean up user data
        context.user_data.pop('roll_number', None)
        context.user_data.pop('html_content', None)
        
    else:
        # Invalid response
        await update.message.reply_text(
            "❓ **Please respond with:**\n• **Yes** or **Y** - for PDF\n• **No** or **N** - to skip\n\nTry again:",
            parse_mode='Markdown'
        )
        
        # Keep the awaiting_pdf_confirmation flag active
        context.user_data['awaiting_pdf_confirmation'] = True

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors."""
    logger.error(f"Exception while handling an update: {context.error}")
    
    try:
        await update.message.reply_text(
            "❌ **An unexpected error occurred**\n\n"
            "Please try again later. If the problem persists, the website might be temporarily unavailable."
        )
    except Exception:
        # If we can't even send an error message, just log it
        logger.error("Could not send error message to user")

def main() -> None:
    """Start the bot."""
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    
    # Add PDF confirmation handler (must come before roll number handler)
    # application.add_handler(MessageHandler(
    #     filters.TEXT & ~filters.COMMAND & filters.Regex(r'^(yes|y|no|n)$', re.IGNORECASE),
    #     handle_pdf_confirmation
    # ))
    
    # # Updated roll number handler to exclude yes/no responses
    # application.add_handler(MessageHandler(
    #     filters.TEXT & ~filters.COMMAND & ~filters.Regex(r'^(yes|y|no|n)$', re.IGNORECASE),
    #     handle_roll_number
    # ))
    application.add_handler(MessageHandler(
    filters.TEXT & ~filters.COMMAND & filters.Regex(r'(?i)^(yes|y|no|n)$'),
    handle_pdf_confirmation
    ))

    application.add_handler(MessageHandler(
    filters.TEXT & ~filters.COMMAND & ~filters.Regex(r'(?i)^(yes|y|no|n)$'),
    handle_roll_number
    ))

    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the bot
    print("🤖 Vishnu CGPA Bot is starting...")
    print("Press Ctrl+C to stop the bot")
    
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"❌ Error starting bot: {e}")

if __name__ == '__main__':
    main()