import os
import logging
import re
from io import BytesIO
from typing import Dict
import requests
from bs4 import BeautifulSoup
from fpdf import FPDF
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Load BOT_TOKEN from environment variable
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Constants
RESULTS_URL = "https://vishnu.edu.in/Results.php"
logging.basicConfig(level=logging.INFO)
session_data: Dict[int, Dict] = {}  # Tracks user roll numbers and data

class CGPAExtractor:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'text/html,application/xhtml+xml',
        })

    def get_html(self, roll):
        try:
            response = self.session.get(f"{RESULTS_URL}?rollno={roll}", timeout=10)
            response.raise_for_status()
            return response.text
        except Exception as e:
            logging.error(f"Error fetching HTML: {e}")
            return None

    def extract_data(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        text = soup.get_text().lower()

        # Check for invalid roll number
        if any(err in text for err in ["not found", "invalid", "no result"]):
            return None, None

        # Parse tables for marks
        tables = soup.find_all("table")
        semesters = []
        for table in tables:
            rows = table.find_all("tr")
            semester = []
            for row in rows:
                cols = [td.get_text(strip=True) for td in row.find_all("td")]
                if cols and len(cols) >= 2:
                    semester.append(cols)
            if semester:
                semesters.append(semester)

        # Try to extract CGPA
        cgpa_match = re.search(r'cgpa\s*:?[\s]*([\d.]+)', text)
        cgpa = cgpa_match.group(1) if cgpa_match else "-"

        return semesters, cgpa

    def generate_pdf(self, roll, semesters, cgpa):
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(0, 10, f"Marksheet for {roll}", ln=True, align='C')

        pdf.set_font("Arial", size=12)
        for idx, semester in enumerate(semesters, 1):
            pdf.ln(5)
            pdf.set_font("Arial", 'B', 12)
            pdf.cell(0, 10, f"Semester {idx}", ln=True)
            pdf.set_font("Arial", size=11)
            for row in semester:
                line = ' | '.join(row)
                pdf.cell(0, 8, line, ln=True)

        pdf.ln(5)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, f"Final CGPA: {cgpa}", ln=True)

        pdf_buffer = BytesIO()
        pdf.output(pdf_buffer)
        pdf_buffer.seek(0)
        return pdf_buffer

extractor = CGPAExtractor()

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip().lower()

    # Step 1: User sent roll number
    if re.match(r'^[0-9a-zA-Z]{10}$', text):
        html = extractor.get_html(text)
        if not html:
            await update.message.reply_text("❌ Failed to fetch data. Try again later.")
            return

        semesters, cgpa = extractor.extract_data(html)
        if not semesters:
            await update.message.reply_text("❌ No results found. Check the roll number.")
            return

        # Store user session
        session_data[user_id] = {
            "roll": text,
            "semesters": semesters,
            "cgpa": cgpa
        }

        await update.message.reply_text(
            f"✅ *Roll Number:* `{text}`\n📊 *CGPA:* `{cgpa}`\n\n📄 Do you want the full PDF marksheet?\nJust reply with `yes` or `pdf`.",
            parse_mode='Markdown'
        )

    # Step 2: User asked for PDF
    elif text in ("yes", "pdf") and user_id in session_data:
        data = session_data[user_id]
        pdf_file = extractor.generate_pdf(data["roll"], data["semesters"], data["cgpa"])
        await update.message.reply_document(
            document=pdf_file,
            filename=f"{data['roll']}_marksheet.pdf",
            caption="📎 Here's your PDF marksheet!"
        )

    else:
        await update.message.reply_text("❌ Please send a valid roll number to begin.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Send your roll number to get your CGPA. Example: 21A91A0501")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()

if __name__ == '__main__':
    main()
