from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import anthropic, base64, json, os
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-in-production-xyz987')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///app.db').replace('postgres://', 'postgresql://')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')

# ── MODELS ────────────────────────────────────────────────────────────────────
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default='user')  # 'admin' or 'user'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, pw): self.password_hash = generate_password_hash(pw)
    def check_password(self, pw): return check_password_hash(self.password_hash, pw)

with app.app_context():
    db.create_all()
    # Create default admin if not exists
    if not User.query.filter_by(username='admin').first():
        u = User(username='admin', role='admin')
        u.set_password('admin123')
        db.session.add(u)
        db.session.commit()

# ── AUTH ──────────────────────────────────────────────────────────────────────
def logged_in():
    return 'user_id' in session

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        data = request.form if request.form else (request.get_json() or {})
        u = User.query.filter_by(username=data.get('username')).first()
        if u and u.check_password(data.get('password', '')):
            session['user_id'] = u.id
            session['username'] = u.username
            session['role'] = u.role
            if request.is_json:
                return jsonify({'ok': True, 'username': u.username, 'role': u.role})
            return redirect('/')
        error = 'Invalid username or password'
        if request.is_json:
            return jsonify({'error': error}), 401
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/api/me')
def me():
    if not logged_in(): return jsonify({'error': 'Not logged in'}), 401
    return jsonify({'username': session['username'], 'role': session['role']})

# ── ADMIN: USER MANAGEMENT ────────────────────────────────────────────────────
@app.route('/api/users', methods=['GET'])
def list_users():
    if not logged_in() or session.get('role') != 'admin': return jsonify({'error': 'Admin only'}), 403
    users = User.query.all()
    return jsonify([{'id': u.id, 'username': u.username, 'role': u.role} for u in users])

@app.route('/api/users', methods=['POST'])
def create_user():
    if not logged_in() or session.get('role') != 'admin': return jsonify({'error': 'Admin only'}), 403
    data = request.get_json()
    if User.query.filter_by(username=data['username']).first():
        return jsonify({'error': 'Username already exists'}), 400
    u = User(username=data['username'], role=data.get('role', 'user'))
    u.set_password(data['password'])
    db.session.add(u)
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/users/<int:uid>', methods=['DELETE'])
def delete_user(uid):
    if not logged_in() or session.get('role') != 'admin': return jsonify({'error': 'Admin only'}), 403
    u = User.query.get_or_404(uid)
    db.session.delete(u)
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/users/<int:uid>/password', methods=['PUT'])
def change_password(uid):
    if not logged_in() or session.get('role') != 'admin': return jsonify({'error': 'Admin only'}), 403
    data = request.get_json()
    u = User.query.get_or_404(uid)
    u.set_password(data['password'])
    db.session.commit()
    return jsonify({'ok': True})

# ── EXTRACT ───────────────────────────────────────────────────────────────────
@app.route('/api/extract', methods=['POST'])
def extract():
    if not logged_in(): return jsonify({'error': 'Not logged in'}), 401
    if not ANTHROPIC_API_KEY: return jsonify({'error': 'API key not configured'}), 500

    data = request.get_json()
    b64 = data['b64']
    mime = data['mime']
    filename = data['filename']

    content = []
    if mime.startswith('image/'):
        content.append({'type': 'image', 'source': {'type': 'base64', 'media_type': mime, 'data': b64}})
    elif mime == 'application/pdf':
        content.append({'type': 'document', 'source': {'type': 'base64', 'media_type': 'application/pdf', 'data': b64}})

    content.append({'type': 'text', 'text': f'''Extract every field from this tax invoice. Return ONLY valid JSON — no markdown:
{{
  "invoice_no":"","invoice_date":"",
  "seller":"","seller_gstin":"","seller_fssai":"",
  "buyer":"","buyer_gstin":"","buyer_fssai":"","buyer_address":"","buyer_state":"",
  "inv_qty_total":0,"inv_taxable_total":0,"inv_cgst_total":0,"inv_sgst_total":0,"inv_grand_total":0,
  "lines":[{{
    "sl_no":"","description":"","hsn":"","mrp":0,"qty":0,"unit":"","rate":0,
    "discount":0,"amount":0,"taxable_amt":0,"cgst_rate":0,"cgst_amt":0,
    "sgst_rate":0,"sgst_amt":0,"total_amt":0
  }}]
}}
Rules:
- Include ALL line items across ALL pages
- mrp and rate: numbers only
- discount: number only, no % symbol
- Do NOT include subtotal or grand total as line items
- filename for reference: {filename}'''})

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(model='claude-sonnet-4-20250514', max_tokens=4000,
                                      messages=[{'role': 'user', 'content': content}])
        raw = ''.join(b.text for b in resp.content if hasattr(b, 'text'))
        parsed = json.loads(raw.replace('```json', '').replace('```', '').strip())
        rows = []
        for l in parsed.get('lines', []):
            rows.append({
                'invoice_no': parsed.get('invoice_no', filename),
                'invoice_date': parsed.get('invoice_date', ''),
                'seller': parsed.get('seller', ''), 'seller_gstin': parsed.get('seller_gstin', ''),
                'seller_fssai': parsed.get('seller_fssai', ''),
                'buyer': parsed.get('buyer', ''), 'buyer_gstin': parsed.get('buyer_gstin', ''),
                'buyer_fssai': parsed.get('buyer_fssai', ''), 'buyer_address': parsed.get('buyer_address', ''),
                'buyer_state': parsed.get('buyer_state', ''),
                'inv_qty_total': float(parsed.get('inv_qty_total') or 0),
                'inv_taxable_total': float(parsed.get('inv_taxable_total') or 0),
                'inv_cgst_total': float(parsed.get('inv_cgst_total') or 0),
                'inv_sgst_total': float(parsed.get('inv_sgst_total') or 0),
                'inv_grand_total': float(parsed.get('inv_grand_total') or 0),
                'sl_no': l.get('sl_no', ''), 'description': l.get('description', ''),
                'hsn': l.get('hsn', ''), 'mrp': float(l.get('mrp') or 0),
                'qty': float(l.get('qty') or 0), 'unit': l.get('unit', ''),
                'rate': float(l.get('rate') or 0), 'discount': float(l.get('discount') or 0),
                'amount': float(l.get('amount') or 0), 'taxable_amt': float(l.get('taxable_amt') or 0),
                'cgst_rate': float(l.get('cgst_rate') or 0), 'cgst_amt': float(l.get('cgst_amt') or 0),
                'sgst_rate': float(l.get('sgst_rate') or 0), 'sgst_amt': float(l.get('sgst_amt') or 0),
                'total_amt': float(l.get('total_amt') or 0),
            })
        return jsonify({'rows': rows})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── PAGES ─────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    if not logged_in(): return redirect('/login')
    return render_template('app.html', username=session['username'], role=session['role'])

@app.route('/admin')
def admin():
    if not logged_in() or session.get('role') != 'admin': return redirect('/')
    return render_template('admin.html', username=session['username'])

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

