import logging
import re
import os
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

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
    raise ValueError("BOT_TOKEN environment variable not set.")

RESULTS_URL = "https://vishnu.edu.in/Results.php"

class CGPAExtractor:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        })

    def get_cgpa(self, roll_number: str) -> dict:
        try:
            roll_number = roll_number.strip().upper()
            if not roll_number:
                return {'success': False, 'message': 'Please provide a valid roll number.'}

            result = self._try_post_request(roll_number)
            if result['success']:
                return result

            result = self._try_get_request(roll_number)
            if result['success']:
                return result

            return {'success': False, 'message': 'Unable to retrieve results.'}

        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return {'success': False, 'message': 'An unexpected error occurred.'}

    def _try_post_request(self, roll_number: str) -> dict:
        try:
            response = self.session.get(RESULTS_URL, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            form = soup.find('form')
            if not form:
                return {'success': False, 'message': 'Form not found'}

            field_name = None
            input_field = soup.find('input', {'type': 'text'})
            if input_field and input_field.get('name'):
                field_name = input_field.get('name')

            if not field_name:
                return {'success': False, 'message': 'Roll number input field not found'}

            form_data = {field_name: roll_number}
            action = form.get('action', RESULTS_URL)
            response = self.session.post(action, data=form_data, timeout=15)
            response.raise_for_status()
            return self._extract_cgpa_from_html(response.text, roll_number)

        except Exception as e:
            logger.error(f"POST request failed: {e}")
            return {'success': False, 'message': 'POST request failed'}

    def _try_get_request(self, roll_number: str) -> dict:
        try:
            url = f"{RESULTS_URL}?rollno={roll_number}"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return self._extract_cgpa_from_html(response.text, roll_number)

        except Exception as e:
            logger.error(f"GET request failed: {e}")
            return {'success': False, 'message': 'GET request failed'}

    def _extract_cgpa_from_html(self, html: str, roll_number: str) -> dict:
        try:
            soup = BeautifulSoup(html, 'html.parser')
            text_content = soup.get_text().lower()

            if any(indicator in text_content for indicator in ['not found', 'invalid', 'error', 'no results', 'no record']):
                return {'success': False, 'message': f'Roll number {roll_number} not found or results unavailable.'}

            cgpa_patterns = [r'cgpa\s*:?\s*(\d+\.?\d*)', r'c\.?g\.?p\.?a\.?\s*:?\s*(\d+\.?\d*)']
            for pattern in cgpa_patterns:
                match = re.search(pattern, text_content, re.IGNORECASE)
                if match:
                    cgpa = match.group(1)
                    return {'success': True, 'cgpa': cgpa, 'message': f'CGPA for roll number {roll_number}: {cgpa}'}

            return {'success': False, 'message': f'CGPA information not found for roll number {roll_number}.'}

        except Exception as e:
            logger.error(f"Error extracting CGPA: {e}")
            return {'success': False, 'message': 'Error processing results page.'}

cgpa_extractor = CGPAExtractor()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    welcome_message = """
🎓 **Welcome to Vishnu CGPA Bot!** 🎓
📝 **How to use:**
Simply send me your roll number and I'll fetch your CGPA for you.
**Example:**
Just type: `21A91A0501` or `20A91A0234`
⚡ **Quick and Easy!**
    """
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    """
    await update.message.reply_text(help_message, parse_mode='Markdown')

async def handle_roll_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_input = update.message.text.strip()
    if not user_input or not re.match(r'^[A-Za-z0-9]+$', user_input):
        await update.message.reply_text("❌ Please provide a valid roll number.\n\nExample: `21A91A0501`", parse_mode='Markdown')
        return

    processing_message = await update.message.reply_text(f"🔍 **Processing roll number:** `{user_input}`\n⏳ Please wait...", parse_mode='Markdown')

    try:
        result = cgpa_extractor.get_cgpa(user_input)
        if result['success']:
            success_message = f"✅ **Results Found!**\n🎓 **Roll Number:** `{user_input}`\n📊 **CGPA:** `{result['cgpa']}`"
            await processing_message.edit_text(success_message.strip(), parse_mode='Markdown')
        else:
            error_message = f"❌ **Unable to retrieve CGPA**\n🔢 **Roll Number:** `{user_input}`\n⚠️ **Issue:** {result['message']}"
            await processing_message.edit_text(error_message.strip(), parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error processing roll number {user_input}: {e}")
        await processing_message.edit_text(f"❌ **Error occurred**\nRoll number: `{user_input}`\nPlease try again later.", parse_mode='Markdown')

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Exception while handling an update: {context.error}")
    await update.message.reply_text("❌ **An unexpected error occurred**\n\nPlease try again later.")

def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_roll_number))
    application.add_error_handler(error_handler)

    print("🤖 Vishnu CGPA Bot is starting...")
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"❌ Error starting bot: {e}")

if __name__ == '__main__':
    main()
