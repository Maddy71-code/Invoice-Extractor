# Invoice Extractor — Web App

## Deploy to Render.com (Free)

### Step 1 — Put this code on GitHub
1. Go to github.com → sign up free
2. Click "New repository" → name it "invoice-extractor" → Create
3. Upload all these files (drag and drop into GitHub)

### Step 2 — Deploy on Render
1. Go to render.com → sign up free
2. Click "New" → "Web Service"
3. Connect your GitHub → select "invoice-extractor"
4. Fill in:
   - Name: invoice-extractor
   - Runtime: Python 3
   - Build command: pip install -r requirements.txt
   - Start command: gunicorn app:app
5. Add Environment Variables:
   - ANTHROPIC_API_KEY = your_key_here
   - SECRET_KEY = any_random_string_here
6. Click "Create Web Service"

### Step 3 — Share the link
Render gives you a link like: https://invoice-extractor.onrender.com
Share this with your staff.

## Default login
- Username: admin
- Password: admin123
⚠ Change this immediately after first login via Manage Users

## Adding staff accounts
1. Log in as admin
2. Click "Manage users" in the top right
3. Add each staff member with their own username and password

## Features
- Upload PDF, JPG, PNG, Excel, CSV invoices
- AI reads and extracts all fields
- Staff picks which fields to include
- Download as Excel or CSV
- Each user has their own login
- Admin can add/remove users
