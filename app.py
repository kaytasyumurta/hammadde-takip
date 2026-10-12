# app.py - Çok Firmalı, Lisanslı ve Kantar Entegreli Hammadde Yönetim Sistemi
import os
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template_string, request,렐, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
import sqlalchemy as sa
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "hammadde_kantar_pro_gizli_2026")

db_url = os.environ.get("DATABASE_URL", "sqlite:///hammadde_kantar_pro.db")
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- VERİTABANI MODELLERİ (MULTI-TENANT & LİSANS) ---
class Firm(db.Model):
    __tablename__ = 'firms'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(150), nullable=False)
    license_start = db.Column(db.DateTime, default=datetime.utcnow)
    license_days = db.Column(db.Integer, default=30)
    status = db.Column(db.String(20), default='active') # active, expired, suspended
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class LicenseKey(db.Model):
    __tablename__ = 'license_keys'
    id = db.Column(db.Integer, primary_key=True)
    firm_id = db.Column(db.Integer, db.ForeignKey('firms.id'), nullable=False)
    key_code = db.Column(db.String(100), unique=True, nullable=False)
    days_to_add = db.Column(db.Integer, nullable=False)
    is_used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    firm = db.relationship('Firm', backref='license_keys')

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    firm_id = db.Column(db.Integer, db.ForeignKey('firms.id'), nullable=True) # Superadmin için null
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False, default='personel') # super_admin, firma_yoneticisi, kantar_personeli, satin_alma
    status = db.Column(db.String(20), nullable=False, default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    firm = db.relationship('Firm', backref='users')

class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    firm_id = db.Column(db.Integer, db.ForeignKey('firms.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)

class RawMaterial(db.Model):
    __tablename__ = 'raw_materials'
    id = db.Column(db.Integer, primary_key=True)
    firm_id = db.Column(db.Integer, db.ForeignKey('firms.id'), nullable=False)
    code = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    unit = db.Column(db.String(20), nullable=False, default='ton')

class Supplier(db.Model):
    __tablename__ = 'suppliers'
    id = db.Column(db.Integer, primary_key=True)
    firm_id = db.Column(db.Integer, db.ForeignKey('firms.id'), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    contact_person = db.Column(db.String(100))
    phone = db.Column(db.String(50))
    city = db.Column(db.String(50))

class SupplyOrder(db.Model):
    __tablename__ = 'supply_orders'
    id = db.Column(db.Integer, primary_key=True)
    firm_id = db.Column(db.Integer, db.ForeignKey('firms.id'), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=False)
    material_id = db.Column(db.Integer, db.ForeignKey('raw_materials.id'), nullable=False)
    target_amount = db.Column(db.Float, nullable=False) # Planlanan tonaj
    delivered_amount = db.Column(db.Float, default=0.0) # Gerçekleşen tonaj
    unit_price = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), default='TL')
    shipping_model = db.Column(db.String(30), default='separate') # separate, included
    shipping_cost = db.Column(db.Float, default=0.0)
    start_date = db.Column(db.String(20))
    end_date = db.Column(db.String(20))
    status = db.Column(db.String(30), default='Aktif') # Aktif, Tamamlandı, İptal
    notes = db.Column(db.Text)

    supplier = db.relationship('Supplier', backref='orders')
    material = db.relationship('RawMaterial', backref='orders')

class ScaleRecord(db.Model):
    __tablename__ = 'scale_records'
    id = db.Column(db.Integer, primary_key=True)
    firm_id = db.Column(db.Integer, db.ForeignKey('firms.id'), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey('supply_orders.id'), nullable=False)
    date = db.Column(db.String(20), nullable=False)
    plate = db.Column(db.String(30), nullable=False)
    driver = db.Column(db.String(100))
    gross_weight = db.Column(db.Float, nullable=False) # Brüt
    tare_weight = db.Column(db.Float, nullable=False)  # Dara
    net_weight = db.Column(db.Float, nullable=False)   # Net Tonaj
    shipping_cost = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default='Onaylandı')

    order = db.relationship('SupplyOrder', backref='scale_records')

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    firm_id = db.Column(db.Integer, db.ForeignKey('firms.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(50), nullable=False)
    details = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# --- İLK KURULUM & DEMO VERİLER ---
with app.app_context():
    db.create_all()
    # Süper Admin Oluşturma
    if not User.query.filter_by(role='super_admin').first():
        sa_user = User(
            username='superadmin',
            email='admin@hammaddepro.com',
            password_hash=generate_password_hash('Admin.123456'),
            role='super_admin',
            status='active'
        )
        db.session.add(sa_user)
        db.session.commit()
    
    # Örnek Firma (KAYMER) Oluşturma
    if not Firm.query.filter_by(code='KAYMER').first():
        kaymer_firm = Firm(code='KAYMER', name='KAYMER A.Ş.', license_days=30, status='active')
        db.session.add(kaymer_firm)
        db.session.commit()

        # Kaymer Firma Yöneticisi
        mgr = User(
            firm_id=kaymer_firm.id,
            username='kaymer_yonetici',
            email='yonetici@kaymer.com',
            password_hash=generate_password_hash('123456'),
            role='firma_yoneticisi',
            status='active'
        )
        db.session.add(mgr)
        
        # Örnek Kategori ve Hammadde
        cat = Category(firm_id=kaymer_firm.id, name='Tahıllar')
        db.session.add(cat)
        db.session.commit()

        mat = RawMaterial(firm_id=kaymer_firm.id, code='MISIR-01', name='Mısır', unit='ton', category_id=cat.id)
        sup = Supplier(firm_id=kaymer_firm.id, name='A Firması Tarım', contact_person='Ahmet Bey', phone='5320000000', city='Kayseri')
        db.session.add_all([mat, sup])
        db.session.commit()

        # Örnek Tedarik Emri (1000 Ton Mısır)
        order = SupplyOrder(
            firm_id=kaymer_firm.id,
            supplier_id=sup.id,
            material_id=mat.id,
            target_amount=1000.0,
            delivered_amount=0.0,
            unit_price=15.50,
            currency='TL',
            shipping_model='separate',
            shipping_cost=750.0,
            start_date='2026-01-01',
            end_date='2026-12-31',
            status='Aktif'
        )
        db.session.add(order)
        db.session.commit()

def log_action(firm_id, user_id, action, details):
    db.session.add(AuditLog(firm_id=firm_id, user_id=user_id, action=action, details=details))
    db.session.commit()

# --- DEKORATÖRLER ---
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash("Lütfen önce giriş yapın.", "error")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def license_check(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') == 'super_admin':
            return f(*args, **kwargs)
        
        firm_id = session.get('firm_id')
        if not firm_id:
            return redirect(url_for('login'))
        
        firm = Firm.query.get(firm_id)
        if not firm or firm.status == 'suspended':
            flash("Firma hesabınız askıya alınmıştır.", "error")
            return redirect(url_for('logout'))
        
        expiry_date = firm.license_start + timedelta(days=firm.license_days)
        if datetime.utcnow() > expiry_date:
            return render_template_string(EXPIRED_LICENSE_TEMPLATE, firm=firm)
        return f(*args, **kwargs)
    return decorated

def tr_format(value):
    if value is None:
        return ""
    try:
        val = float(value)
        return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return str(value)

app.jinja_env.filters['tr_num'] = tr_format

# --- ŞABLONLAR & ARAYÜZ (DARK/LIGHT + SOL MENÜ + TÜM ÖZELLİKLER) ---
EXPIRED_LICENSE_TEMPLATE = """
<!DOCTYPE html>
<html lang="tr" class="dark">
<head><script src="https://cdn.tailwindcss.com"></script><title>Lisans Sona Erdi</title></head>
<body class="bg-slate-950 text-white flex items-center justify-center min-h-screen">
    <div class="bg-slate-900 border border-slate-800 p-8 rounded-2xl max-w-md text-center space-y-4 shadow-2xl">
        <div class="w-16 h-16 bg-rose-500/10 text-rose-500 rounded-2xl flex items-center justify-center mx-auto text-2xl font-bold">⚠️</div>
        <h1 class="text-xl font-bold">Firma Lisans Süresi Doldu</h1>
        <p class="text-xs text-slate-400">{{ firm.name }} firmasına ait lisans süresi sona ermiştir. Verileriniz güvendedir ancak operasyonel işlemlere devam etmek için lisans anahtarı giriniz.</p>
        <form action="{{ url_for('renew_license') }}" method="POST" class="space-y-3 pt-2">
            <input type="text" name="key_code" placeholder="Lisans Uzatma Anahtarı" required class="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-xs text-white outline-none focus:border-blue-500">
            <button type="submit" class="w-full py-3 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold rounded-xl shadow-lg">Lisansı Aktifleştir</button>
        </form>
        <a href="{{ url_for('logout') }}" class="block text-xs text-slate-500 hover:underline pt-2">Çıkış Yap</a>
    </div>
</body>
</html>
"""

BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="tr" x-data="{ 
    darkMode: localStorage.getItem('darkMode') !== 'false', 
    lang: localStorage.getItem('lang') || 'tr',
    settingsOpen: false 
}" :class="{ 'dark': darkMode }">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hammadde & Kantar Pro</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: {
                        navy: { 950: '#060B19', 900: '#0B132B', 800: '#111C3A', 700: '#1A294C', 600: '#233763' }
                    }
                }
            }
        }
    </script>
    <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Plus Jakarta Sans', sans-serif; }
        .custom-scrollbar::-webkit-scrollbar { width: 6px; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: #1A294C; border-radius: 4px; }
    </style>
</head>
<body class="bg-slate-100 dark:bg-navy-950 text-slate-800 dark:text-slate-100 min-h-screen flex flex-col antialiased">
    <!-- ÜST BAR -->
    <header class="h-16 bg-white dark:bg-navy-900 border-b border-slate-200 dark:border-navy-800 px-6 flex items-center justify-between sticky top-0 z-40 shadow-sm">
        <a href="{{ url_for('index') }}" class="flex items-center gap-3">
            <div class="w-9 h-9 rounded-xl bg-blue-600 flex items-center justify-center text-white font-black text-xl shadow-lg shadow-blue-600/30">H</div>
            <div>
                <span class="font-bold text-base tracking-tight block leading-tight">Hammadde & Kantar Pro</span>
                <span class="text-[9px] text-slate-400 font-semibold uppercase tracking-wider block">{% if session.get('firm_name') %}{{ session.get('firm_name') }}{% else %}SÜPER YÖNETİCİ{% endif %}</span>
            </div>
        </a>

        {% if session.get('user_id') and session.get('status') == 'active' and session.get('role') != 'super_admin' %}
        <nav class="hidden md:flex items-center gap-6 text-xs font-semibold">
            <a href="{{ url_for('index') }}" class="py-2 {{ 'text-blue-600 dark:text-blue-400 border-b-2 border-blue-500' if active_page=='home' else 'text-slate-500 dark:text-slate-400' }}">Ana Sayfa</a>
            <a href="{{ url_for('supply_orders_view') }}" class="py-2 {{ 'text-blue-600 dark:text-blue-400 border-b-2 border-blue-500' if active_page=='orders' else 'text-slate-500 dark:text-slate-400' }}">Tedarik Yönetimi</a>
            <a href="{{ url_for('scale_records_view') }}" class="py-2 {{ 'text-blue-600 dark:text-blue-400 border-b-2 border-blue-500' if active_page=='scale' else 'text-slate-500 dark:text-slate-400' }}">Kantar & Araç Girişi</a>
            <a href="{{ url_for('suppliers') }}" class="py-2 {{ 'text-blue-600 dark:text-blue-400 border-b-2 border-blue-500' if active_page=='suppliers' else 'text-slate-500 dark:text-slate-400' }}">Firmalar</a>
            <a href="{{ url_for('materials') }}" class="py-2 {{ 'text-blue-600 dark:text-blue-400 border-b-2 border-blue-500' if active_page=='materials' else 'text-slate-500 dark:text-slate-400' }}">Hammaddeler</a>
        </nav>
        {% endif %}

        <div class="flex items-center gap-3 relative">
            <div class="relative">
                <button @click="settingsOpen = !settingsOpen" class="w-9 h-9 rounded-xl bg-slate-100 dark:bg-navy-800 text-slate-600 dark:text-slate-300 flex items-center justify-center border border-slate-200 dark:border-navy-700">
                    <i class="fa-solid fa-gear text-sm"></i>
                </button>
                <div x-show="settingsOpen" @click.outside="settingsOpen = false" class="absolute right-0 mt-2 w-48 bg-white dark:bg-navy-900 border border-slate-200 dark:border-navy-800 rounded-2xl shadow-xl p-3 z-50 space-y-2" style="display: none;">
                    <div class="text-[10px] font-bold text-slate-400 uppercase px-2">Dil / Language</div>
                    <div class="grid grid-cols-2 gap-1 bg-slate-100 dark:bg-navy-950 p-1 rounded-xl">
                        <button @click="lang='tr'; localStorage.setItem('lang', 'tr'); settingsOpen=false" :class="lang=='tr' ? 'bg-blue-600 text-white' : 'text-slate-600 dark:text-slate-400'" class="py-1 rounded-lg text-xs font-bold">TR</button>
                        <button @click="lang='en'; localStorage.setItem('lang', 'en'); settingsOpen=false" :class="lang=='en' ? 'bg-blue-600 text-white' : 'text-slate-600 dark:text-slate-400'" class="py-1 rounded-lg text-xs font-bold">EN</button>
                    </div>
                </div>
            </div>

            <button @click="darkMode = !darkMode; localStorage.setItem('darkMode', darkMode)" class="w-9 h-9 rounded-xl bg-slate-100 dark:bg-navy-800 text-slate-600 dark:text-slate-300 flex items-center justify-center border border-slate-200 dark:border-navy-700">
                <i class="fa-solid" :class="darkMode ? 'fa-sun text-amber-400' : 'fa-moon text-slate-700'"></i>
            </button>

            {% if session.get('user_id') %}
            <div class="flex items-center gap-2 bg-slate-50 dark:bg-navy-800 px-3 py-1.5 rounded-xl border border-slate-200 dark:border-navy-700">
                <div class="w-7 h-7 rounded-lg bg-blue-600 text-white font-bold flex items-center justify-center text-xs">{{ session.get('username')[:2].upper() }}</div>
                <div class="text-left leading-none">
                    <div class="text-xs font-bold">{{ session.get('username') }}</div>
                    <span class="text-[9px] text-purple-600 dark:text-purple-400 uppercase font-semibold">{{ session.get('role') }}</span>
                </div>
            </div>
            <a href="{{ url_for('logout') }}" class="w-9 h-9 rounded-xl bg-rose-50 dark:bg-rose-950/60 text-rose-600 dark:text-rose-400 flex items-center justify-center border border-rose-100 dark:border-rose-900/40">
                <i class="fa-solid fa-power-off text-sm"></i>
            </a>
            {% endif %}
        </div>
    </header>

    <div class="flex flex-1 overflow-hidden">
        {% if session.get('user_id') and session.get('role') != 'super_admin' %}
        <aside class="w-60 bg-white dark:bg-navy-900/60 border-r border-slate-200 dark:border-navy-800 p-4 flex flex-col justify-between hidden lg:flex">
            <div class="space-y-2">
                <a href="{{ url_for('index') }}" class="flex items-center gap-3 px-3 py-2.5 rounded-xl text-xs font-semibold {{ 'bg-blue-600 text-white' if active_page=='home' else 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-navy-800' }}">
                    <i class="fa-solid fa-house text-sm w-5"></i> Ana Sayfa
                </a>
                <a href="{{ url_for('supply_orders_view') }}" class="flex items-center gap-3 px-3 py-2.5 rounded-xl text-xs font-semibold {{ 'bg-blue-600 text-white' if active_page=='orders' else 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-navy-800' }}">
                    <i class="fa-solid fa-chart-line text-sm w-5"></i> Tedarik Yönetimi
                </a>
                <a href="{{ url_for('scale_records_view') }}" class="flex items-center gap-3 px-3 py-2.5 rounded-xl text-xs font-semibold {{ 'bg-blue-600 text-white' if active_page=='scale' else 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-navy-800' }}">
                    <i class="fa-solid fa-truck text-sm w-5"></i> Kantar & Araç Girişi
                </a>
                <a href="{{ url_for('suppliers') }}" class="flex items-center gap-3 px-3 py-2.5 rounded-xl text-xs font-semibold {{ 'bg-blue-600 text-white' if active_page=='suppliers' else 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-navy-800' }}">
                    <i class="fa-solid fa-briefcase text-sm w-5"></i> Tedarikçi Firmalar
                </a>
                <a href="{{ url_for('materials') }}" class="flex items-center gap-3 px-3 py-2.5 rounded-xl text-xs font-semibold {{ 'bg-blue-600 text-white' if active_page=='materials' else 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-navy-800' }}">
                    <i class="fa-solid fa-leaf text-sm w-5"></i> Hammaddeler
                </a>
            </div>
            <div class="pt-6 border-t border-slate-200 dark:border-navy-800 text-[10px] text-slate-400">
                Hammadde & Kantar Altyapısı &copy; 2026
            </div>
        </aside>
        {% endif %}

        <main class="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-6">
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for cat, msg in messages %}
                        <div class="p-4 rounded-xl text-xs font-semibold border {{ 'bg-emerald-50 border-emerald-200 text-emerald-800 dark:bg-emerald-950 dark:border-emerald-800 dark:text-emerald-300' if cat=='success' else 'bg-rose-50 border-rose-200 text-rose-800 dark:bg-rose-950 dark:border-rose-800 dark:text-rose-300' }}">
                            <i class="fa-solid fa-circle-info mr-2"></i> {{ msg }}
                        </div>
                    {% endfor %}
                {% endif %}
            {% endwith %}
            CONTENT_PLACEHOLDER
        </main>
    </div>
</body>
</html>
"""

def render_page(content_html, active_page='home', **kwargs):
    return render_template_string(BASE_TEMPLATE.replace("CONTENT_PLACEHOLDER", content_html), active_page=active_page, **kwargs)

# --- ROTALAR ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            session['status'] = user.status
            if user.firm:
                session['firm_id'] = user.firm.id
                session['firm_name'] = user.firm.name
            
            if user.role == 'super_admin':
                return redirect(url_for('super_admin_dashboard'))
            return redirect(url_for('index'))
        flash("Kullanıcı adı veya şifre hatalı.", "error")
    
    return render_template_string("""
    <!DOCTYPE html>
    <html lang="tr" class="dark">
    <head><script src="https://cdn.tailwindcss.com"></script><title>Giriş Yap</title></head>
    <body class="bg-slate-950 text-white flex items-center justify-center min-h-screen">
        <form method="POST" class="bg-slate-900 border border-slate-800 p-8 rounded-2xl max-w-md w-full space-y-4 shadow-xl">
            <h1 class="text-xl font-bold text-center">Hammadde & Kantar Girişi</h1>
            <div><label class="text-xs text-slate-400">Kullanıcı Adı</label><input type="text" name="username" required class="w-full mt-1 px-3 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-xs"></div>
            <div><label class="text-xs text-slate-400">Şifre</label><input type="password" name="password" required class="w-full mt-1 px-3 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-xs"></div>
            <button type="submit" class="w-full py-3 bg-blue-600 hover:bg-blue-500 rounded-xl text-xs font-semibold shadow-lg shadow-blue-600/30">Giriş Yap</button>
        </form>
    </body>
    </html>
    """)

@app.route('/logout')
def logout():
    session.clear()
    flash("Oturum kapatıldı.", "success")
    return redirect(url_for('login'))

@app.route('/')
@login_required
@license_check
def index():
    if session.get('role') == 'super_admin':
        return redirect(url_for('super_admin_dashboard'))
    
    firm_id = session.get('firm_id')
    active_orders = SupplyOrder.query.filter_by(firm_id=firm_id, status='Aktif').count()
    completed_orders = SupplyOrder.query.filter_by(firm_id=firm_id, status='Tamamlandı').count()
    scale_count = ScaleRecord.query.filter_by(firm_id=firm_id).count()

    return render_page("""
    <div class="space-y-6">
        <div class="bg-white dark:bg-navy-900 border border-slate-200 dark:border-navy-800 p-6 rounded-2xl flex justify-between items-center shadow-sm">
            <div>
                <h1 class="text-xl font-bold">Firma Kontrol Paneli</h1>
                <p class="text-xs text-slate-500 dark:text-slate-400 mt-1">Hoş geldiniz, {{ session.get('username') }}</p>
            </div>
            <a href="{{ url_for('scale_records_view') }}" class="px-4 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-semibold shadow-lg shadow-blue-600/20 inline-flex items-center gap-2">
                <i class="fa-solid fa-truck"></i> Yeni Araç Kantar Kaydı
            </a>
        </div>
        
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div class="bg-white dark:bg-navy-900 border border-slate-200 dark:border-navy-800 p-5 rounded-2xl flex items-center justify-between shadow-sm">
                <div><p class="text-xs font-semibold text-slate-500 dark:text-slate-400">Aktif Tedarikler</p><p class="text-3xl font-bold text-blue-600 dark:text-blue-400 mt-1">{{ active_orders }}</p></div>
                <div class="w-12 h-12 bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 rounded-xl flex items-center justify-center text-lg"><i class="fa-solid fa-chart-line"></i></div>
            </div>
            <div class="bg-white dark:bg-navy-900 border border-slate-200 dark:border-navy-800 p-5 rounded-2xl flex items-center justify-between shadow-sm">
                <div><p class="text-xs font-semibold text-slate-500 dark:text-slate-400">Tamamlanan Tedarikler</p><p class="text-3xl font-bold text-emerald-600 dark:text-emerald-400 mt-1">{{ completed_orders }}</p></div>
                <div class="w-12 h-12 bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 rounded-xl flex items-center justify-center text-lg"><i class="fa-solid fa-check"></i></div>
            </div>
            <div class="bg-white dark:bg-navy-900 border border-slate-200 dark:border-navy-800 p-5 rounded-2xl flex items-center justify-between shadow-sm">
                <div><p class="text-xs font-semibold text-slate-500 dark:text-slate-400">Toplam Kantar Kaydı</p><p class="text-3xl font-bold text-amber-600 dark:text-amber-400 mt-1">{{ scale_count }}</p></div>
                <div class="w-12 h-12 bg-amber-50 dark:bg-amber-500/10 text-amber-600 dark:text-amber-400 rounded-xl flex items-center justify-center text-lg"><i class="fa-solid fa-weight-scale"></i></div>
            </div>
        </div>
    </div>
    """, active_page='home', active_orders=active_orders, completed_orders=completed_orders, scale_count=scale_count)

# --- SÜPER YÖNETİCİ PANELİ ---
@app.route('/superadmin')
@login_required
def super_admin_dashboard():
    if session.get('role') != 'super_admin':
        return redirect(url_for('index'))
    firms = Firm.query.all()
    return render_template_string("""
    <!DOCTYPE html>
    <html lang="tr" class="dark">
    <head><script src="https://cdn.tailwindcss.com"></script><title>Super Admin Paneli</title></head>
    <body class="bg-slate-950 text-white p-8 space-y-6">
        <div class="flex justify-between items-center max-w-5xl mx-auto">
            <h1 class="text-xl font-bold">Süper Yönetici - Firma & Lisans Yönetimi</h1>
            <a href="{{ url_for('logout') }}" class="text-rose-400 text-xs">Çıkış</a>
        </div>
        <div class="max-w-5xl mx-auto bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4 shadow-xl">
            <h2 class="text-sm font-bold">Yeni Firma Oluştur & Lisans Tanımla</h2>
            <form action="{{ url_for('sa_add_firm') }}" method="POST" class="grid grid-cols-3 gap-3">
                <input type="text" name="name" placeholder="Firma Adı" required class="px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-xs">
                <input type="text" name="code" placeholder="Firma Kodu (Örn: ABC)" required class="px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-xs">
                <input type="number" name="days" placeholder="Lisans Süresi (Gün)" value="30" required class="px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-xs">
                <button type="submit" class="col-span-3 py-2.5 bg-blue-600 text-white rounded-xl text-xs font-semibold">Firma ve Lisans Kaydet</button>
            </form>
        </div>
        <div class="max-w-5xl mx-auto bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
            <table class="w-full text-left text-xs">
                <thead class="bg-slate-950 text-slate-400 border-b border-slate-800">
                    <tr><th class="p-4">Firma Adı</th><th class="p-4">Kod</th><th class="p-4">Lisans Süresi</th><th class="p-4">Durum</th><th class="p-4 text-right">İşlem</th></tr>
                </thead>
                <tbody class="divide-y divide-slate-800">
                    {% for f in firms %}
                    <tr>
                        <td class="p-4 font-bold">{{ f.name }}</td>
                        <td class="p-4 text-blue-400">{{ f.code }}</td>
                        <td class="p-4">{{ f.license_days }} Gün</td>
                        <td class="p-4 text-emerald-400">{{ f.status }}</td>
                        <td class="p-4 text-right">
                            <a href="{{ url_for('sa_generate_key', firm_id=f.id) }}" class="px-3 py-1 bg-blue-600/20 text-blue-400 rounded-lg text-[11px]">Uzatma Anahtarı Üret</a>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """, firms=firms)

@app.route('/superadmin/add-firm', methods=['POST'])
@login_required
def sa_add_firm():
    if session.get('role') != 'super_admin':
        return redirect(url_for('index'))
    f = Firm(
        name=request.form.get('name').strip(),
        code=request.form.get('code').strip().upper(),
        license_days=int(request.form.get('days', 30)),
        status='active'
    )
    db.session.add(f)
    db.session.commit()
    flash("Firma ve lisansı başarıyla oluşturuldu.", "success")
    return redirect(url_for('super_admin_dashboard'))

@app.route('/superadmin/generate-key/<int:firm_id>')
@login_required
def sa_generate_key(firm_id):
    if session.get('role') != 'super_admin':
        return redirect(url_for('index'))
    firm = Firm.query.get_or_404(firm_id)
    key_code = f"KEY-{firm.code}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    lk = LicenseKey(firm_id=firm.id, key_code=key_code, days_to_add=30, is_used=False)
    db.session.add(lk)
    db.session.commit()
    flash(f"{firm.name} için Uzatma Anahtarı üretildi: {key_code}", "success")
    return redirect(url_for('super_admin_dashboard'))

@app.route('/renew-license', methods=['POST'])
@login_required
def renew_license():
    key_code = request.form.get('key_code', '').strip()
    lk = LicenseKey.query.filter_by(key_code=key_code, is_used=False).first()
    if lk:
        firm = Firm.query.get(lk.firm_id)
        firm.license_days += lk.days_to_add
        lk.is_used = True
        db.session.commit()
        flash(f"Lisans başarıyla {lk.days_to_add} gün uzatıldı.", "success")
        return redirect(url_for('index'))
    flash("Geçersiz veya daha önce kullanılmış lisans anahtarı.", "error")
    return redirect(url_for('index'))

# --- TEDARİK YÖNETİMİ MODÜLÜ ---
@app.route('/supply-orders')
@login_required
@license_check
def supply_orders_view():
    firm_id = session.get('firm_id')
    orders = SupplyOrder.query.filter_by(firm_id=firm_id).order_by(SupplyOrder.id.desc()).all()
    suppliers = Supplier.query.filter_by(firm_id=firm_id).all()
    materials = RawMaterial.query.filter_by(firm_id=firm_id).all()

    return render_page("""
    <div class="space-y-4" x-data="{ openAdd: false }">
        <div class="bg-white dark:bg-navy-900 border border-slate-200 dark:border-navy-800 p-5 rounded-2xl flex justify-between items-center shadow-sm">
            <div>
                <h1 class="text-lg font-bold">Hammadde Tedarik Yönetimi</h1>
                <p class="text-xs text-slate-500">Planlanan ve gerçekleşen tonajlar ile ilerleme takibi.</p>
            </div>
            <button @click="openAdd = true" class="px-4 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-semibold shadow-md">
                <i class="fa-solid fa-plus mr-1"></i> Yeni Tedarik Ekle
            </button>
        </div>

        <div class="bg-white dark:bg-navy-900 border border-slate-200 dark:border-navy-800 rounded-2xl overflow-hidden shadow-sm">
            <table class="w-full text-left border-collapse">
                <thead>
                    <tr class="bg-slate-50 dark:bg-navy-950/60 border-b border-slate-200 dark:border-navy-800 text-[11px] font-bold text-slate-400 uppercase">
                        <th class="p-4">Tedarikçi</th>
                        <th class="p-4">Ürün</th>
                        <th class="p-4">Hedef Miktar</th>
                        <th class="p-4">Gelen Miktar</th>
                        <th class="p-4">İlerleme Oranı</th>
                        <th class="p-4">Birim Fiyat</th>
                        <th class="p-4">Durum</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-slate-100 dark:divide-navy-800 text-xs font-semibold">
                    {% for o in orders %}
                    {% set pct = (o.delivered_amount / o.target_amount * 100) if o.target_amount > 0 else 0 %}
                    <tr class="hover:bg-slate-50 dark:hover:bg-navy-800/30">
                        <td class="p-4 font-bold">{{ o.supplier.name }}</td>
                        <td class="p-4 text-blue-600 dark:text-blue-400">{{ o.material.name }}</td>
                        <td class="p-4">{{ o.target_amount | tr_num }} {{ o.material.unit }}</td>
                        <td class="p-4 font-bold text-emerald-600 dark:text-emerald-400">{{ o.delivered_amount | tr_num }} {{ o.material.unit }}</td>
                        <td class="p-4">
                            <div class="w-32 bg-slate-200 dark:bg-navy-800 h-2.5 rounded-full overflow-hidden">
                                <div class="bg-blue-600 h-full" style="width: {{ pct if pct <= 100 else 100 }}%"></div>
                            </div>
                            <span class="text-[10px] text-slate-400 mt-1 block">{{ "%.1f"|format(pct) }}% (Kalan: {{ "%.2f"|format(o.target_amount - o.delivered_amount) }})</span>
                        </td>
                        <td class="p-4">{{ o.unit_price | tr_num }} {{ o.currency }}/{{ o.material.unit }}</td>
                        <td class="p-4"><span class="px-2.5 py-1 rounded-full text-[10px] bg-emerald-50 dark:bg-emerald-950 text-emerald-600 font-bold">{{ o.status }}</span></td>
                    </tr>
                    {% else %}
                    <tr><td colspan="7" class="p-8 text-center text-slate-400">Kayıtlı tedarik emri bulunamadı.</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <!-- MODAL: YENİ TEDARİK -->
        <div x-show="openAdd" class="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50" style="display: none;">
            <div class="bg-white dark:bg-navy-900 p-6 rounded-2xl max-w-lg w-full border border-slate-200 dark:border-navy-800 space-y-4 shadow-2xl" @click.outside="openAdd = false">
                <h3 class="text-base font-bold">Yeni Hammadde Tedarik Emri</h3>
                <form action="{{ url_for('add_supply_order') }}" method="POST" class="space-y-3">
                    <div class="grid grid-cols-2 gap-3">
                        <div><label class="block text-xs text-slate-500 mb-1">Tedarikçi</label><select name="supplier_id" class="w-full px-3 py-2 bg-slate-50 dark:bg-navy-950 border border-slate-200 dark:border-navy-800 rounded-xl text-xs">{% for s in suppliers %}<option value="{{ s.id }}">{{ s.name }}</option>{% endfor %}</select></div>
                        <div><label class="block text-xs text-slate-500 mb-1">Hammadde</label><select name="material_id" class="w-full px-3 py-2 bg-slate-50 dark:bg-navy-950 border border-slate-200 dark:border-navy-800 rounded-xl text-xs">{% for m in materials %}<option value="{{ m.id }}">{{ m.name }}</option>{% endfor %}</select></div>
                    </div>
                    <div class="grid grid-cols-2 gap-3">
                        <div><label class="block text-xs text-slate-500 mb-1">Hedef Miktar (Ton)</label><input type="number" step="0.01" name="target_amount" required class="w-full px-3 py-2 bg-slate-50 dark:bg-navy-950 border border-slate-200 dark:border-navy-800 rounded-xl text-xs"></div>
                        <div><label class="block text-xs text-slate-500 mb-1">Alış Fiyatı</label><input type="number" step="0.01" name="unit_price" required class="w-full px-3 py-2 bg-slate-50 dark:bg-navy-950 border border-slate-200 dark:border-navy-800 rounded-xl text-xs"></div>
                    </div>
                    <div class="flex justify-end gap-2 pt-2">
                        <button type="button" @click="openAdd = false" class="px-4 py-2 bg-slate-200 dark:bg-navy-800 rounded-xl text-xs">İptal</button>
                        <button type="submit" class="px-4 py-2 bg-blue-600 text-white rounded-xl text-xs">Oluştur</button>
                    </div>
                </form>
            </div>
        </div>
    </div>
    """, active_page='orders', orders=orders, suppliers=suppliers, materials=materials)

@app.route('/supply-orders/add', methods=['POST'])
@login_required
@license_check
def add_supply_order():
    firm_id = session.get('firm_id')
    o = SupplyOrder(
        firm_id=firm_id,
        supplier_id=request.form.get('supplier_id'),
        material_id=request.form.get('material_id'),
        target_amount=float(request.form.get('target_amount')),
        unit_price=float(request.form.get('unit_price')),
        status='Aktif'
    )
    db.session.add(o)
    db.session.commit()
    flash("Tedarik emri eklendi.", "success")
    return redirect(url_for('supply_orders_view'))

# --- KANTAR VE ARAÇ GİRİŞ MODÜLÜ ---
@app.route('/scale-records')
@login_required
@license_check
def scale_records_view():
    firm_id = session.get('firm_id')
    records = ScaleRecord.query.filter_by(firm_id=firm_id).order_by(ScaleRecord.id.desc()).all()
    active_orders = SupplyOrder.query.filter_by(firm_id=firm_id, status='Aktif').all()

    return render_page("""
    <div class="space-y-4" x-data="{ openAdd: false }">
        <div class="bg-white dark:bg-navy-900 border border-slate-200 dark:border-navy-800 p-5 rounded-2xl flex justify-between items-center shadow-sm">
            <div>
                <h1 class="text-lg font-bold">Kantar ve Araç Giriş Modülü</h1>
                <p class="text-xs text-slate-500">Brüt - Dara ölçümleri ve otomatik net tonaj güncellemesi.</p>
            </div>
            <button @click="openAdd = true" class="px-4 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-semibold shadow-md">
                <i class="fa-solid fa-truck mr-1"></i> Yeni Araç Kaydı (Kantar)
            </button>
        </div>

        <div class="bg-white dark:bg-navy-900 border border-slate-200 dark:border-navy-800 rounded-2xl overflow-hidden shadow-sm">
            <table class="w-full text-left border-collapse">
                <thead>
                    <tr class="bg-slate-50 dark:bg-navy-950/60 border-b border-slate-200 dark:border-navy-800 text-[11px] font-bold text-slate-400 uppercase">
                        <th class="p-4">Tarih</th>
                        <th class="p-4">Plaka / Şoför</th>
                        <th class="p-4">Tedarikçi / Ürün</th>
                        <th class="p-4">Brüt (Ton)</th>
                        <th class="p-4">Dara (Ton)</th>
                        <th class="p-4">Net Tonaj</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-slate-100 dark:divide-navy-800 text-xs font-semibold">
                    {% for r in records %}
                    <tr class="hover:bg-slate-50 dark:hover:bg-navy-800/30">
                        <td class="p-4 text-slate-400">{{ r.date }}</td>
                        <td class="p-4 font-bold">{{ r.plate }} <span class="block text-[10px] text-slate-400">{{ r.driver or '-' }}</span></td>
                        <td class="p-4">{{ r.order.supplier.name }} <span class="block text-[10px] text-blue-500">{{ r.order.material.name }}</span></td>
                        <td class="p-4">{{ r.gross_weight | tr_num }}</td>
                        <td class="p-4">{{ r.tare_weight | tr_num }}</td>
                        <td class="p-4 font-bold text-emerald-600 dark:text-emerald-400 text-sm">{{ r.net_weight | tr_num }} Ton</td>
                    </tr>
                    {% else %}
                    <tr><td colspan="6" class="p-8 text-center text-slate-400">Kantar kaydı bulunamadı.</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <!-- MODAL: KANTAR GİRİŞİ -->
        <div x-show="openAdd" class="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50" style="display: none;" x-data="{ gross: 0, tare: 0 }">
            <div class="bg-white dark:bg-navy-900 p-6 rounded-2xl max-w-lg w-full border border-slate-200 dark:border-navy-800 space-y-4 shadow-2xl" @click.outside="openAdd = false">
                <h3 class="text-base font-bold">Kantar Araç Tartım Kaydı</h3>
                <form action="{{ url_for('add_scale_record') }}" method="POST" class="space-y-3">
                    <div><label class="block text-xs text-slate-500 mb-1">İlişkili Tedarik Emri</label><select name="order_id" required class="w-full px-3 py-2 bg-slate-50 dark:bg-navy-950 border border-slate-200 dark:border-navy-800 rounded-xl text-xs">{% for o in active_orders %}<option value="{{ o.id }}">{{ o.supplier.name }} - {{ o.material.name }} (Kalan: {{ o.target_amount - o.delivered_amount }} Ton)</option>{% endfor %}</select></div>
                    <div class="grid grid-cols-2 gap-3">
                        <div><label class="block text-xs text-slate-500 mb-1">Plaka</label><input type="text" name="plate" required class="w-full px-3 py-2 bg-slate-50 dark:bg-navy-950 border border-slate-200 dark:border-navy-800 rounded-xl text-xs"></div>
                        <div><label class="block text-xs text-slate-500 mb-1">Şoför</label><input type="text" name="driver" class="w-full px-3 py-2 bg-slate-50 dark:bg-navy-950 border border-slate-200 dark:border-navy-800 rounded-xl text-xs"></div>
                    </div>
                    <div class="grid grid-cols-2 gap-3">
                        <div><label class="block text-xs text-slate-500 mb-1">Brüt Ağırlık (Ton)</label><input type="number" step="0.001" name="gross_weight" x-model.number="gross" required class="w-full px-3 py-2 bg-slate-50 dark:bg-navy-950 border border-slate-200 dark:border-navy-800 rounded-xl text-xs"></div>
                        <div><label class="block text-xs text-slate-500 mb-1">Dara Ağırlığı (Ton)</label><input type="number" step="0.001" name="tare_weight" x-model.number="tare" required class="w-full px-3 py-2 bg-slate-50 dark:bg-navy-950 border border-slate-200 dark:border-navy-800 rounded-xl text-xs"></div>
                    </div>
                    <div class="p-3 bg-blue-50 dark:bg-blue-950/40 rounded-xl flex justify-between items-center text-xs">
                        <span class="font-semibold text-slate-600 dark:text-slate-300">Hesaplanan Net Tonaj:</span>
                        <span class="font-bold text-blue-600 dark:text-blue-400 text-sm" x-text="(gross - tare > 0 ? (gross - tare).toFixed(3) : 0) + ' Ton'"></span>
                    </div>
                    <div class="flex justify-end gap-2 pt-2">
                        <button type="button" @click="openAdd = false" class="px-4 py-2 bg-slate-200 dark:bg-navy-800 rounded-xl text-xs">İptal</button>
                        <button type="submit" class="px-4 py-2 bg-blue-600 text-white rounded-xl text-xs">Kaydet & Tedariğe Ekle</button>
                    </div>
                </form>
            </div>
        </div>
    </div>
    """, active_page='scale', records=records, active_orders=active_orders)

@app.route('/scale-records/add', methods=['POST'])
@login_required
@license_check
def add_scale_record():
    firm_id = session.get('firm_id')
    order_id = int(request.form.get('order_id'))
    gross = float(request.form.get('gross_weight'))
    tare = float(request.form.get('tare_weight'))
    net = gross - tare

    if net <= 0:
        flash("Net tonaj 0 veya negatif olamaz.", "error")
        return redirect(url_for('scale_records_view'))

    record = ScaleRecord(
        firm_id=firm_id,
        order_id=order_id,
        date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        plate=request.form.get('plate').strip().upper(),
        driver=request.form.get('driver'),
        gross_weight=gross,
        tare_weight=tare,
        net_weight=net,
        created_by=session.get('user_id')
    )
    db.session.add(record)

    # Tedarik emrini otomatik güncelle
    order = SupplyOrder.query.get(order_id)
    if order:
        order.delivered_amount += net
        if order.delivered_amount >= order.target_amount:
            order.status = 'Tamamlandı'

    db.session.commit()
    flash(f"Kantar kaydı eklendi. Net {net:.3f} Ton tedariğe işlendi.", "success")
    return redirect(url_for('scale_records_view'))

# --- TEMEL FİRMA & HAMMADDE ROTALARI ---
@app.route('/suppliers')
@login_required
@license_check
def suppliers():
    firm_id = session.get('firm_id')
    suppliers_list = Supplier.query.filter_by(firm_id=firm_id).all()
    return render_page("""
    <div class="space-y-4" x-data="{ openAdd: false }">
        <div class="bg-white dark:bg-navy-900 border border-slate-200 dark:border-navy-800 p-5 rounded-2xl flex justify-between items-center shadow-sm">
            <div><h1 class="text-lg font-bold">Tedarikçi Firmalar</h1><p class="text-xs text-slate-500">Kayıtlı tedarikçi portföyü.</p></div>
            <button @click="openAdd = true" class="px-4 py-2.5 bg-blue-600 text-white rounded-xl text-xs font-semibold shadow-md"><i class="fa-solid fa-plus mr-1"></i> Yeni Firma</button>
        </div>
        <div class="bg-white dark:bg-navy-900 border border-slate-200 dark:border-navy-800 rounded-xl overflow-hidden">
            <table class="w-full text-left border-collapse text-xs">
                <thead><tr class="bg-slate-50 dark:bg-navy-950/60 border-b border-slate-200 dark:border-navy-800 text-slate-400 uppercase font-bold"><th class="p-4">Firma Adı</th><th class="p-4">Yetkili</th><th class="p-4">Telefon</th><th class="p-4">Şehir</th></tr></thead>
                <tbody class="divide-y divide-slate-100 dark:divide-navy-800 font-semibold">
                    {% for s in suppliers %}
                    <tr><td class="p-4 font-bold">{{ s.name }}</td><td class="p-4 text-slate-400">{{ s.contact_person or '-' }}</td><td class="p-4 text-slate-400">{{ s.phone or '-' }}</td><td class="p-4 text-slate-400">{{ s.city or '-' }}</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        <div x-show="openAdd" class="fixed inset-0 bg-black/60 flex items-center justify-center p-4 z-50" style="display: none;">
            <div class="bg-white dark:bg-navy-900 p-6 rounded-2xl max-w-md w-full border border-navy-800 space-y-3 shadow-xl" @click.outside="openAdd = false">
                <h3 class="text-base font-bold">Yeni Tedarikçi Firma</h3>
                <form action="{{ url_for('add_supplier') }}" method="POST" class="space-y-3">
                    <div><label class="block text-xs text-slate-500 mb-1">Firma Adı</label><input type="text" name="name" required class="w-full px-3 py-2 bg-slate-50 dark:bg-navy-950 border border-slate-200 dark:border-navy-800 rounded-xl text-xs"></div>
                    <div><label class="block text-xs text-slate-500 mb-1">Yetkili</label><input type="text" name="contact_person" class="w-full px-3 py-2 bg-slate-50 dark:bg-navy-950 border border-slate-200 dark:border-navy-800 rounded-xl text-xs"></div>
                    <div><label class="block text-xs text-slate-500 mb-1">Telefon</label><input type="text" name="phone" class="w-full px-3 py-2 bg-slate-50 dark:bg-navy-950 border border-slate-200 dark:border-navy-800 rounded-xl text-xs"></div>
                    <div><label class="block text-xs text-slate-500 mb-1">Şehir</label><input type="text" name="city" class="w-full px-3 py-2 bg-slate-50 dark:bg-navy-950 border border-slate-200 dark:border-navy-800 rounded-xl text-xs"></div>
                    <div class="flex justify-end gap-2 pt-2"><button type="button" @click="openAdd = false" class="px-4 py-2 bg-slate-200 dark:bg-navy-800 rounded-xl text-xs">İptal</button><button type="submit" class="px-4 py-2 bg-blue-600 text-white rounded-xl text-xs">Kaydet</button></div>
                </form>
            </div>
        </div>
    </div>
    """, active_page='suppliers', suppliers=suppliers_list)

@app.route('/suppliers/add', methods=['POST'])
@login_required
@license_check
def add_supplier():
    s = Supplier(
        firm_id=session.get('firm_id'),
        name=request.form.get('name').strip(),
        contact_person=request.form.get('contact_person'),
        phone=request.form.get('phone'),
        city=request.form.get('city')
    )
    db.session.add(s)
    db.session.commit()
    flash("Firma eklendi.", "success")
    return redirect(url_for('suppliers'))

@app.route('/materials')
@login_required
@license_check
def materials():
    firm_id = session.get('firm_id')
    materials_list = RawMaterial.query.filter_by(firm_id=firm_id).all()
    return render_page("""
    <div class="space-y-4" x-data="{ openAdd: false }">
        <div class="bg-white dark:bg-navy-900 border border-slate-200 dark:border-navy-800 p-5 rounded-2xl flex justify-between items-center shadow-sm">
            <div><h1 class="text-lg font-bold">Hammadde Envanteri</h1><p class="text-xs text-slate-500">Tanımlı hammaddeler.</p></div>
            <button @click="openAdd = true" class="px-4 py-2.5 bg-blue-600 text-white rounded-xl text-xs font-semibold shadow-md"><i class="fa-solid fa-plus mr-1"></i> Yeni Hammadde</button>
        </div>
        <div class="bg-white dark:bg-navy-900 border border-slate-200 dark:border-navy-800 rounded-xl overflow-hidden">
            <table class="w-full text-left border-collapse text-xs">
                <thead><tr class="bg-slate-50 dark:bg-navy-950/60 border-b border-slate-200 dark:border-navy-800 text-slate-400 uppercase font-bold"><th class="p-4">Kod</th><th class="p-4">Hammadde Adı</th><th class="p-4">Birim</th></tr></thead>
                <tbody class="divide-y divide-slate-100 dark:divide-navy-800 font-semibold">
                    {% for m in materials %}
                    <tr><td class="p-4 font-bold text-blue-500">{{ m.code }}</td><td class="p-4">{{ m.name }}</td><td class="p-4 uppercase text-slate-400">{{ m.unit }}</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        <div x-show="openAdd" class="fixed inset-0 bg-black/60 flex items-center justify-center p-4 z-50" style="display: none;">
            <div class="bg-white dark:bg-navy-900 p-6 rounded-2xl max-w-md w-full border border-navy-800 space-y-3 shadow-xl" @click.outside="openAdd = false">
                <h3 class="text-base font-bold">Yeni Hammadde Tanımı</h3>
                <form action="{{ url_for('add_material') }}" method="POST" class="space-y-3">
                    <div><label class="block text-xs text-slate-500 mb-1">Kod</label><input type="text" name="code" required class="w-full px-3 py-2 bg-slate-50 dark:bg-navy-950 border border-slate-200 dark:border-navy-800 rounded-xl text-xs"></div>
                    <div><label class="block text-xs text-slate-500 mb-1">Adı</label><input type="text" name="name" required class="w-full px-3 py-2 bg-slate-50 dark:bg-navy-950 border border-slate-200 dark:border-navy-800 rounded-xl text-xs"></div>
                    <div><label class="block text-xs text-slate-500 mb-1">Birim</label><select name="unit" class="w-full px-3 py-2 bg-slate-50 dark:bg-navy-950 border border-slate-200 dark:border-navy-800 rounded-xl text-xs"><option value="ton">ton</option><option value="kg">kg</option><option value="litre">litre</option></select></div>
                    <div class="flex justify-end gap-2 pt-2"><button type="button" @click="openAdd = false" class="px-4 py-2 bg-slate-200 dark:bg-navy-800 rounded-xl text-xs">İptal</button><button type="submit" class="px-4 py-2 bg-blue-600 text-white rounded-xl text-xs">Kaydet</button></div>
                </form>
            </div>
        </div>
    </div>
    """, active_page='materials', materials=materials_list)

@app.route('/materials/add', methods=['POST'])
@login_required
@license_check
def add_material():
    m = RawMaterial(
        firm_id=session.get('firm_id'),
        code=request.form.get('code').strip().upper(),
        name=request.form.get('name').strip(),
        unit=request.form.get('unit')
    )
    db.session.add(m)
    db.session.commit()
    flash("Hammadde eklendi.", "success")
    return redirect(url_for('materials'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)
