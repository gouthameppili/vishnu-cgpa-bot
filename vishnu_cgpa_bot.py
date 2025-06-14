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

BOT_TOKEN = os.getenv("BOT_TOKEN")
logging.basicConfig(level=logging.INFO)
session_data: Dict[int, Dict] = {}

class CGPAExtractor:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'text/html,application/xhtml+xml',
            'Content-Type': 'application/x-www-form-urlencoded'
        })

    def get_html(self, roll):
        try:
            url = f"https://vishnu.edu.in/Results.php?rollno={roll}"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return response.text
        except Exception as e:
            logging.error(f"Error fetching HTML for {roll}: {e}")
            return None

    def extract_data(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        text = soup.get_text().lower()

        if any(x in text for x in ["not found", "invalid", "no result"]):
            return None, None

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

        cgpa_match = re.search(r'(?:cgpa|cumulative grade point average).*?(\d+\.\d+)', text)
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
    text = update.message.text.strip().upper()

    if re.match(r'^[0-9A-Z]{10}$', text):
        await update.message.reply_text(f"🔄 Processing roll number: {text}\nPlease wait while I fetch your CGPA...")
        html = extractor.get_html(text)
        if not html:
            await update.message.reply_text("❌ Failed to fetch result. Website may be down or format changed.")
            return

        semesters, cgpa = extractor.extract_data(html)
        if not semesters:
            await update.message.reply_text(f"❌ Unable to retrieve CGPA\n⚠️ Please check your roll number or try again later.")
            return

        session_data[user_id] = {
            "roll": text,
            "semesters": semesters,
            "cgpa": cgpa
        }

        await update.message.reply_text(
            f"✅ *Roll Number:* `{text}`\n📊 *CGPA:* `{cgpa}`\n\n📄 Do you want the full PDF marksheet?\nJust reply with `yes` or `pdf`.",
            parse_mode='Markdown'
        )

    elif text.lower() in ("yes", "pdf") and user_id in session_data:
        data = session_data[user_id]
        pdf_file = extractor.generate_pdf(data["roll"], data["semesters"], data["cgpa"])
        await update.message.reply_document(
            document=pdf_file,
            filename=f"{data['roll']}_marksheet.pdf",
            caption="📎 Here's your PDF marksheet!"
        )

    else:
        await update.message.reply_text("❌ Please send a valid 10-character roll number to begin.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Send your 10-character roll number to get your CGPA and marksheet. Example: 23PA1A4235")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()

if __name__ == '__main__':
    main()
