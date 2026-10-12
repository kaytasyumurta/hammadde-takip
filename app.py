# app.py - Hammadde Fiyat ve Takip Sistemi (Birebir Arayüz Sürümü)
import os
from datetime import datetime
from functools import wraps
from flask import Flask, render_template_string, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
import sqlalchemy as sa
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "hammadde_takip_gizli_anahtar_2026")

db_url = os.environ.get("DATABASE_URL", "sqlite:///hammadde_sistemi.db")
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- VERİTABANI MODELLERİ ---
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='personel')
    status = db.Column(db.String(20), nullable=False, default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(50), nullable=False)
    details = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

class RawMaterial(db.Model):
    __tablename__ = 'raw_materials'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(150), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'))
    unit = db.Column(db.String(20), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default='active')
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    category = db.relationship('Category', backref='materials')
    creator = db.relationship('User', backref='materials')

class Supplier(db.Model):
    __tablename__ = 'suppliers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    contact_person = db.Column(db.String(100))
    phone = db.Column(db.String(50))
    email = db.Column(db.String(120))
    address = db.Column(db.Text)
    city = db.Column(db.String(50))
    tax_no = db.Column(db.String(50))
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default='active')
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    creator = db.relationship('User', backref='suppliers')

class Price(db.Model):
    __tablename__ = 'prices'
    id = db.Column(db.Integer, primary_key=True)
    material_id = db.Column(db.Integer, db.ForeignKey('raw_materials.id'), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=False)
    date = db.Column(db.String(20), nullable=False)
    currency = db.Column(db.String(10), nullable=False, default='TL')
    unit_price = db.Column(db.Float, nullable=False)
    shipping_status = db.Column(db.String(30), nullable=False, default='included')
    shipping_cost = db.Column(db.Float, default=0)
    shipping_excluded = db.Column(db.Float, nullable=False)
    shipping_included = db.Column(db.Float, nullable=False)
    valid_until = db.Column(db.String(20))
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    material = db.relationship('RawMaterial', backref='prices')
    supplier = db.relationship('Supplier', backref='prices')

# --- VERİTABANI KONTROLÜ ---
with app.app_context():
    db.create_all()
    inspector = sa.inspect(db.engine)
    if 'prices' in inspector.get_table_names():
        columns = [c['name'] for c in inspector.get_columns('prices')]
        with db.engine.connect() as conn:
            if 'shipping_status' not in columns:
                conn.execute(sa.text("ALTER TABLE prices ADD COLUMN shipping_status VARCHAR(30) DEFAULT 'included'"))
                conn.commit()

    if Category.query.count() == 0:
        for cat_name in ["Kimyasallar", "Metaller", "Plastikler", "Ambalaj", "Diğer"]:
            db.session.add(Category(name=cat_name))
        db.session.commit()

def log_action(user_id, action, details):
    db.session.add(AuditLog(user_id=user_id, action=action, details=details))
    db.session.commit()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash("Lütfen önce giriş yapın.", "error")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            flash("Bu işlem için Admin yetkisi gerekiyor.", "error")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated

def editor_or_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session or session.get('role') not in ['admin', 'yonetici']:
            flash("Bu işlem için Yönetici veya Admin yetkisi gerekiyor.", "error")
            return redirect(url_for('index'))
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

# --- GÖRSELDEKİ BİREBİR ŞABLON YAPISI ---
BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="tr" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hammadde Pro - Tedarik & Fiyat Takip</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: {
                        navy: {
                            950: '#060B19',
                            900: '#0B132B',
                            800: '#111C3A',
                            700: '#1A294C',
                            600: '#233763'
                        },
                        brand: {
                            500: '#2563EB',
                            600: '#1D4ED8'
                        }
                    }
                }
            }
        }
    </script>
    <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Plus Jakarta Sans', sans-serif; background-color: #060B19; color: #F1F5F9; }
        .custom-scrollbar::-webkit-scrollbar { width: 6px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: #060B19; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: #1A294C; border-radius: 4px; }
    </style>
</head>
<body class="min-h-screen flex flex-col antialiased">
    <!-- ÜST BAR (NAVBAR) -->
    <header class="h-16 bg-navy-900 border-b border-navy-800/80 px-6 flex items-center justify-between sticky top-0 z-40">
        <!-- Logo -->
        <a href="{{ url_for('index') }}" class="flex items-center gap-3">
            <div class="w-9 h-9 rounded-xl bg-blue-600 flex items-center justify-center text-white font-black text-xl shadow-lg shadow-blue-600/30">
                H
            </div>
            <div>
                <span class="font-bold text-base tracking-tight text-white block leading-tight">Hammadde Pro</span>
                <span class="text-[9px] text-slate-400 font-semibold uppercase tracking-wider block">TEDARİK & FİYAT TAKİP</span>
            </div>
        </a>

        <!-- Üst Sekmeler -->
        {% if session.get('user_id') and session.get('status') == 'active' %}
        <nav class="hidden md:flex items-center gap-6 text-xs font-semibold">
            <a href="{{ url_for('materials') }}" class="flex items-center gap-2 py-2 transition-colors {{ 'text-blue-400 border-b-2 border-blue-500' if active_page=='materials' else 'text-slate-400 hover:text-slate-200' }}">
                <i class="fa-solid fa-house text-sm"></i> Hammaddeler
            </a>
            <a href="{{ url_for('suppliers') }}" class="flex items-center gap-2 py-2 transition-colors {{ 'text-blue-400 border-b-2 border-blue-500' if active_page=='suppliers' else 'text-slate-400 hover:text-slate-200' }}">
                <i class="fa-solid fa-boxes-stacked text-sm"></i> Firmalar
            </a>
            <a href="{{ url_for('prices') }}" class="flex items-center gap-2 py-2 transition-colors {{ 'text-blue-400 border-b-2 border-blue-500' if active_page=='prices' else 'text-slate-400 hover:text-slate-200' }}">
                <i class="fa-solid fa-chart-line text-sm"></i> Fiyatlar & Karşılaştırma
            </a>
            {% if session.get('role') in ['admin', 'yonetici'] %}
            <a href="{{ url_for('categories_view') }}" class="flex items-center gap-2 py-2 transition-colors {{ 'text-blue-400 border-b-2 border-blue-500' if active_page=='categories' else 'text-slate-400 hover:text-slate-200' }}">
                <i class="fa-regular fa-folder text-sm"></i> Kategoriler
            </a>
            <a href="{{ url_for('logs') }}" class="flex items-center gap-2 py-2 transition-colors {{ 'text-blue-400 border-b-2 border-blue-500' if active_page=='logs' else 'text-slate-400 hover:text-slate-200' }}">
                <i class="fa-regular fa-clipboard text-sm"></i> Loglar
            </a>
            {% endif %}
            {% if session.get('role') == 'admin' %}
            <a href="{{ url_for('admin_users') }}" class="flex items-center gap-2 py-2 transition-colors {{ 'text-blue-400 border-b-2 border-blue-500' if active_page=='users' else 'text-slate-400 hover:text-slate-200' }}">
                <i class="fa-regular fa-user text-sm"></i> Kullanıcılar
            </a>
            {% endif %}
        </nav>
        {% endif %}

        <!-- Sağ İkonlar & Kullanıcı -->
        <div class="flex items-center gap-3">
            <button class="w-9 h-9 rounded-xl bg-navy-800 text-slate-400 hover:text-white flex items-center justify-center border border-navy-700/50">
                <i class="fa-solid fa-gear text-sm"></i>
            </button>

            {% if session.get('user_id') %}
            <div class="flex items-center gap-2 bg-navy-800/80 px-3 py-1.5 rounded-xl border border-navy-700/60">
                <div class="w-7 h-7 rounded-lg bg-blue-600 text-white font-bold flex items-center justify-center text-xs">
                    {{ session.get('username')[:2].upper() }}
                </div>
                <div class="text-left leading-none">
                    <div class="text-xs font-bold text-white">{{ session.get('username') }}</div>
                    <span class="text-[9px] text-purple-400 uppercase font-semibold">{{ session.get('role') }}</span>
                </div>
            </div>
            <button class="w-9 h-9 rounded-xl bg-navy-800 text-slate-400 hover:text-white flex items-center justify-center border border-navy-700/50">
                <i class="fa-regular fa-sun text-sm"></i>
            </button>
            <a href="{{ url_for('logout') }}" class="w-9 h-9 rounded-xl bg-rose-950/60 text-rose-400 hover:bg-rose-600 hover:text-white flex items-center justify-center border border-rose-900/40 transition-colors">
                <i class="fa-solid fa-power-off text-sm"></i>
            </a>
            {% endif %}
        </div>
    </header>

    <!-- ANA GÖVDE (SOL MENÜ + İÇERİK) -->
    <div class="flex flex-1 overflow-hidden">
        <!-- SOL SIDEBAR -->
        <aside class="w-60 bg-navy-900/60 border-r border-navy-800/80 p-4 flex flex-col justify-between hidden lg:flex">
            <div class="space-y-2">
                <a href="{{ url_for('index') }}" class="flex items-center gap-3 px-3 py-2.5 rounded-xl text-xs font-semibold {{ 'bg-blue-600 text-white' if active_page=='home' else 'text-slate-400 hover:bg-navy-800/50 hover:text-white' }}">
                    <i class="fa-solid fa-house text-sm w-5"></i> Ana Sayfa
                </a>
                <a href="{{ url_for('suppliers') }}" class="flex items-center gap-3 px-3 py-2.5 rounded-xl text-xs font-semibold {{ 'bg-blue-600 text-white shadow-lg shadow-blue-600/30' if active_page=='suppliers' else 'text-slate-400 hover:bg-navy-800/50 hover:text-white' }}">
                    <i class="fa-solid fa-briefcase text-sm w-5"></i> Firma Yönetimi
                </a>
                <a href="{{ url_for('materials') }}" class="flex items-center gap-3 px-3 py-2.5 rounded-xl text-xs font-semibold {{ 'bg-blue-600 text-white' if active_page=='materials' else 'text-slate-400 hover:bg-navy-800/50 hover:text-white' }}">
                    <i class="fa-solid fa-leaf text-sm w-5"></i> Hammaddeler
                </a>
                <a href="{{ url_for('prices') }}" class="flex items-center gap-3 px-3 py-2.5 rounded-xl text-xs font-semibold {{ 'bg-blue-600 text-white' if active_page=='prices' else 'text-slate-400 hover:bg-navy-800/50 hover:text-white' }}">
                    <i class="fa-solid fa-chart-line text-sm w-5"></i> Fiyatlar & Karşılaştırma
                </a>
                <a href="{{ url_for('categories_view') }}" class="flex items-center gap-3 px-3 py-2.5 rounded-xl text-xs font-semibold {{ 'bg-blue-600 text-white' if active_page=='categories' else 'text-slate-400 hover:bg-navy-800/50 hover:text-white' }}">
                    <i class="fa-regular fa-folder text-sm w-5"></i> Kategoriler
                </a>
                <a href="{{ url_for('logs') }}" class="flex items-center gap-3 px-3 py-2.5 rounded-xl text-xs font-semibold {{ 'bg-blue-600 text-white' if active_page=='logs' else 'text-slate-400 hover:bg-navy-800/50 hover:text-white' }}">
                    <i class="fa-regular fa-clock text-sm w-5"></i> Loglar
                </a>
                <a href="{{ url_for('admin_users') }}" class="flex items-center gap-3 px-3 py-2.5 rounded-xl text-xs font-semibold {{ 'bg-blue-600 text-white' if active_page=='users' else 'text-slate-400 hover:bg-navy-800/50 hover:text-white' }}">
                    <i class="fa-regular fa-user text-sm w-5"></i> Kullanıcılar
                </a>
            </div>

            <div class="pt-6 border-t border-navy-800/60 flex items-center gap-2">
                <div class="w-7 h-7 rounded-lg bg-blue-500/10 text-blue-400 flex items-center justify-center text-xs">
                    <i class="fa-solid fa-cubes"></i>
                </div>
                <div class="text-[10px] text-slate-400 leading-tight">
                    Hammadde, Doğru Bilgiyle<br><span class="text-slate-200 font-semibold">Daha Değerli</span>
                </div>
            </div>
        </aside>

        <!-- ORTA İÇERİK ALANI -->
        <main class="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-6">
            <!-- FLASH MESAJLARI -->
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="p-4 rounded-xl text-xs font-semibold border flex items-center gap-3 {{ 'bg-emerald-950/60 border-emerald-800/80 text-emerald-300' if category == 'success' else 'bg-rose-950/60 border-rose-800/80 text-rose-300' }}">
                            <i class="fa-solid {{ 'fa-circle-check text-emerald-400' if category == 'success' else 'fa-circle-exclamation text-rose-400' }}"></i>
                            <span>{{ message }}</span>
                        </div>
                    {% endfor %}
                {% endif %}
            {% endwith %}

            CONTENT_PLACEHOLDER
        </main>
    </div>

    <!-- ALT BİLGİ (FOOTER) -->
    <footer class="bg-navy-900 border-t border-navy-800 px-6 py-3 text-xs text-slate-500 flex justify-between items-center">
        <div>Hammadde Fiyat ve Takip Sistemi &copy; 2026 | Profesyonel Bulut Altyapısı</div>
        <div class="flex items-center gap-2 text-emerald-400 text-[11px] font-medium">
            <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span> Sistem Aktif
        </div>
    </footer>
</body>
</html>
"""

def render_page(content_html, active_page='home', **kwargs):
    full_html = BASE_TEMPLATE.replace("CONTENT_PLACEHOLDER", content_html)
    return render_template_string(full_html, active_page=active_page, **kwargs)

# --- ROUTE'LAR ---
@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    m_count = RawMaterial.query.count()
    s_count = Supplier.query.count()
    p_count = Price.query.count()

    return render_page("""
    <div class="space-y-6">
        <div class="bg-navy-900/80 border border-navy-800/80 p-6 rounded-2xl flex justify-between items-center">
            <div>
                <h1 class="text-xl font-bold text-white">Kontrol Paneli</h1>
                <p class="text-xs text-slate-400 mt-1">Hoş geldiniz, {{ session.get('username') }}</p>
            </div>
            <a href="{{ url_for('prices') }}" class="px-4 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-semibold shadow-lg shadow-blue-600/30 transition-all">
                <i class="fa-solid fa-plus mr-1.5"></i> Yeni Fiyat Ekle
            </a>
        </div>
        
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div class="bg-navy-900/80 border border-navy-800/80 p-5 rounded-2xl flex items-center justify-between">
                <div><p class="text-xs font-semibold text-slate-400">Toplam Hammadde</p><p class="text-2xl font-bold mt-1 text-blue-400">{{ m_count }}</p></div>
                <div class="w-12 h-12 bg-blue-500/10 text-blue-400 rounded-xl flex items-center justify-center text-lg"><i class="fa-solid fa-leaf"></i></div>
            </div>
            <div class="bg-navy-900/80 border border-navy-800/80 p-5 rounded-2xl flex items-center justify-between">
                <div><p class="text-xs font-semibold text-slate-400">Kayıtlı Tedarikçiler</p><p class="text-2xl font-bold mt-1 text-emerald-400">{{ s_count }}</p></div>
                <div class="w-12 h-12 bg-emerald-500/10 text-emerald-400 rounded-xl flex items-center justify-center text-lg"><i class="fa-solid fa-briefcase"></i></div>
            </div>
            <div class="bg-navy-900/80 border border-navy-800/80 p-5 rounded-2xl flex items-center justify-between">
                <div><p class="text-xs font-semibold text-slate-400">Fiyat Kayıtları</p><p class="text-2xl font-bold mt-1 text-amber-400">{{ p_count }}</p></div>
                <div class="w-12 h-12 bg-amber-500/10 text-amber-400 rounded-xl flex items-center justify-center text-lg"><i class="fa-solid fa-chart-line"></i></div>
            </div>
        </div>
    </div>
    """, active_page='home', m_count=m_count, s_count=s_count, p_count=p_count)

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
            log_action(user.id, "LOGIN", f"Giriş yapıldı: {username}")
            flash("Giriş başarılı.", "success")
            return redirect(url_for('index'))
        else:
            flash("Kullanıcı adı veya şifre hatalı.", "error")

    return render_page("""
    <div class="max-w-md mx-auto bg-navy-900 border border-navy-800 p-8 rounded-2xl space-y-6 my-12">
        <h2 class="text-xl font-bold text-center text-white">Giriş Yap</h2>
        <form method="POST" class="space-y-4">
            <div><label class="block text-xs font-semibold text-slate-400 mb-1.5">Kullanıcı Adı</label><input type="text" name="username" required class="w-full px-4 py-2.5 bg-navy-950 border border-navy-800 rounded-xl text-xs text-white outline-none focus:border-blue-500"></div>
            <div><label class="block text-xs font-semibold text-slate-400 mb-1.5">Şifre</label><input type="password" name="password" required class="w-full px-4 py-2.5 bg-navy-950 border border-navy-800 rounded-xl text-xs text-white outline-none focus:border-blue-500"></div>
            <button type="submit" class="w-full py-3 bg-blue-600 hover:bg-blue-500 text-white font-semibold text-xs rounded-xl shadow-lg shadow-blue-600/30">Giriş Yap</button>
        </form>
    </div>
    """, active_page='login')

@app.route('/suppliers')
@login_required
def suppliers():
    search = request.args.get('search', '')
    query = Supplier.query
    if search:
        query = query.filter(db.or_(Supplier.name.ilike(f'%{search}%'), Supplier.city.ilike(f'%{search}%')))
    suppliers_list = query.order_by(Supplier.id.desc()).all()

    return render_page("""
    <div class="space-y-4" x-data="{ openAdd: false }">
        <!-- HEADER KARTI -->
        <div class="bg-navy-900/90 border border-navy-800/80 p-5 rounded-2xl flex justify-between items-center shadow-lg">
            <div class="flex items-center gap-4">
                <div class="w-12 h-12 bg-blue-600/20 text-blue-400 border border-blue-500/30 rounded-2xl flex items-center justify-center text-xl">
                    <i class="fa-solid fa-briefcase"></i>
                </div>
                <div>
                    <h1 class="text-lg font-bold text-white">Firma Yönetimi</h1>
                    <p class="text-xs text-slate-400">Tedarikçi firma portföyünüzü yönetin.</p>
                </div>
            </div>
            <button @click="openAdd = true" class="px-4 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-semibold shadow-lg shadow-blue-600/30 transition-all flex items-center gap-2">
                <i class="fa-solid fa-plus"></i> Yeni Firma
            </button>
        </div>

        <!-- ARAMA VE FİLTRELEME -->
        <form method="GET" class="flex gap-3 items-center">
            <div class="relative flex-1">
                <i class="fa-solid fa-magnifying-glass absolute left-4 top-3 text-slate-500 text-xs"></i>
                <input type="text" name="search" value="{{ search_val }}" placeholder="Firma adı veya şehir..." class="w-full pl-10 pr-4 py-2.5 bg-navy-900/80 border border-navy-800/80 rounded-xl text-xs text-white placeholder-slate-500 outline-none focus:border-blue-500/60 transition-colors">
            </div>
            <button type="submit" class="px-5 py-2.5 bg-navy-900 border border-navy-800/80 hover:bg-navy-800 text-slate-300 rounded-xl text-xs font-semibold flex items-center gap-2">
                <i class="fa-solid fa-filter text-slate-400"></i> Filtrele
            </button>
            <a href="{{ url_for('suppliers') }}" class="px-5 py-2.5 bg-navy-900 border border-navy-800/80 hover:bg-navy-800 text-slate-300 rounded-xl text-xs font-semibold flex items-center gap-2">
                <i class="fa-solid fa-rotate-right text-slate-400"></i> Sıfırla
            </a>
        </form>

        <!-- TABLO -->
        <div class="bg-navy-900/90 border border-navy-800/80 rounded-2xl overflow-hidden shadow-lg">
            <div class="overflow-x-auto">
                <table class="w-full text-left border-collapse">
                    <thead>
                        <tr class="bg-navy-950/60 border-b border-navy-800/80 text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                            <th class="p-4"><i class="fa-solid fa-briefcase mr-2 text-slate-500"></i> FIRMA ADI</th>
                            <th class="p-4"><i class="fa-regular fa-user mr-2 text-slate-500"></i> YETKİLİ</th>
                            <th class="p-4"><i class="fa-solid fa-phone mr-2 text-slate-500"></i> TELEFON</th>
                            <th class="p-4"><i class="fa-solid fa-location-dot mr-2 text-slate-500"></i> ŞEHİR</th>
                            <th class="p-4"><i class="fa-regular fa-circle-dot mr-2 text-slate-500"></i> DURUM</th>
                            <th class="p-4 text-right"><i class="fa-solid fa-gear mr-2 text-slate-500"></i> İŞLEMLER</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-navy-800/60 text-xs font-semibold text-slate-200">
                        {% for s in suppliers %}
                        <tr class="hover:bg-navy-800/30 transition-colors">
                            <td class="p-4 font-bold text-white">{{ s.name }}</td>
                            <td class="p-4 text-slate-400">{{ s.contact_person or '-' }}</td>
                            <td class="p-4 text-slate-400">{{ s.phone or '-' }}</td>
                            <td class="p-4 text-slate-400">{{ s.city or '-' }}</td>
                            <td class="p-4">
                                <span class="px-3 py-1 rounded-full text-[11px] font-bold inline-flex items-center gap-1.5 bg-emerald-950/60 text-emerald-400 border border-emerald-800/50">
                                    <span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span> Aktif
                                </span>
                            </td>
                            <td class="p-4 text-right space-x-2">
                                <a href="{{ url_for('supplier_detail', id=s.id) }}" class="px-3 py-1.5 bg-navy-800 hover:bg-navy-700 text-blue-400 rounded-lg border border-navy-700/50 inline-flex items-center gap-1.5 text-[11px]">
                                    <i class="fa-regular fa-eye"></i> Detay
                                </a>
                                <a href="{{ url_for('edit_supplier', id=s.id) }}" class="px-3 py-1.5 bg-navy-800 hover:bg-navy-700 text-slate-300 rounded-lg border border-navy-700/50 inline-flex items-center gap-1.5 text-[11px]">
                                    <i class="fa-regular fa-pen-to-square"></i> Düzenle
                                </a>
                                <a href="{{ url_for('delete_supplier', id=s.id) }}" onclick="return confirm('Emin misiniz?')" class="px-3 py-1.5 bg-rose-950/40 hover:bg-rose-900/60 text-rose-400 rounded-lg border border-rose-900/40 inline-flex items-center gap-1.5 text-[11px]">
                                    <i class="fa-regular fa-trash-can"></i> Sil
                                </a>
                            </td>
                        </tr>
                        {% else %}
                        <tr><td colspan="6" class="p-8 text-center text-slate-500 font-medium">Kayıtlı firma bulunamadı.</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- MODAL: YENİ FİRMA -->
        <div x-show="openAdd" class="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 z-50" style="display: none;">
            <div class="bg-navy-900 p-6 rounded-2xl max-w-lg w-full border border-navy-800 space-y-4 shadow-2xl" @click.outside="openAdd = false">
                <h3 class="text-base font-bold text-white">Yeni Firma Ekle</h3>
                <form action="{{ url_for('add_supplier') }}" method="POST" class="space-y-3">
                    <div><label class="block text-xs font-semibold text-slate-400 mb-1">Firma Adı</label><input type="text" name="name" required class="w-full px-3 py-2 bg-navy-950 border border-navy-800 rounded-xl text-xs text-white outline-none"></div>
                    <div class="grid grid-cols-2 gap-3">
                        <div><label class="block text-xs font-semibold text-slate-400 mb-1">Yetkili</label><input type="text" name="contact_person" class="w-full px-3 py-2 bg-navy-950 border border-navy-800 rounded-xl text-xs text-white outline-none"></div>
                        <div><label class="block text-xs font-semibold text-slate-400 mb-1">Telefon</label><input type="text" name="phone" class="w-full px-3 py-2 bg-navy-950 border border-navy-800 rounded-xl text-xs text-white outline-none"></div>
                    </div>
                    <div class="grid grid-cols-2 gap-3">
                        <div><label class="block text-xs font-semibold text-slate-400 mb-1">E-posta</label><input type="email" name="email" class="w-full px-3 py-2 bg-navy-950 border border-navy-800 rounded-xl text-xs text-white outline-none"></div>
                        <div><label class="block text-xs font-semibold text-slate-400 mb-1">Şehir</label><input type="text" name="city" class="w-full px-3 py-2 bg-navy-950 border border-navy-800 rounded-xl text-xs text-white outline-none"></div>
                    </div>
                    <div class="flex justify-end gap-2 pt-2">
                        <button type="button" @click="openAdd = false" class="px-4 py-2 bg-navy-800 text-slate-300 rounded-xl text-xs font-semibold">İptal</button>
                        <button type="submit" class="px-4 py-2 bg-blue-600 text-white rounded-xl text-xs font-semibold">Kaydet</button>
                    </div>
                </form>
            </div>
        </div>
    </div>
    """, active_page='suppliers', suppliers=suppliers_list, search_val=search)

@app.route('/suppliers/add', methods=['POST'])
@login_required
def add_supplier():
    s = Supplier(
        name=request.form.get('name').strip(),
        contact_person=request.form.get('contact_person'),
        phone=request.form.get('phone'),
        email=request.form.get('email'),
        city=request.form.get('city'),
        created_by=session.get('user_id')
    )
    db.session.add(s)
    db.session.commit()
    log_action(session['user_id'], "ADD_SUPPLIER", f"Firma eklendi: {s.name}")
    flash("Firma eklendi.", "success")
    return redirect(url_for('suppliers'))

@app.route('/suppliers/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_supplier(id):
    s = Supplier.query.get_or_404(id)
    if request.method == 'POST':
        s.name = request.form.get('name').strip()
        s.contact_person = request.form.get('contact_person')
        s.phone = request.form.get('phone')
        s.city = request.form.get('city')
        db.session.commit()
        flash("Firma güncellendi.", "success")
        return redirect(url_for('suppliers'))
    return render_page("""
    <div class="max-w-md mx-auto bg-navy-900 border border-navy-800 p-6 rounded-2xl space-y-4">
        <h2 class="text-base font-bold text-white">Firma Düzenle</h2>
        <form method="POST" class="space-y-3">
            <div><label class="block text-xs text-slate-400 mb-1">Firma Adı</label><input type="text" name="name" value="{{ s.name }}" required class="w-full px-3 py-2 bg-navy-950 border border-navy-800 rounded-xl text-xs text-white"></div>
            <div><label class="block text-xs text-slate-400 mb-1">Yetkili</label><input type="text" name="contact_person" value="{{ s.contact_person or '' }}" class="w-full px-3 py-2 bg-navy-950 border border-navy-800 rounded-xl text-xs text-white"></div>
            <div><label class="block text-xs text-slate-400 mb-1">Telefon</label><input type="text" name="phone" value="{{ s.phone or '' }}" class="w-full px-3 py-2 bg-navy-950 border border-navy-800 rounded-xl text-xs text-white"></div>
            <div><label class="block text-xs text-slate-400 mb-1">Şehir</label><input type="text" name="city" value="{{ s.city or '' }}" class="w-full px-3 py-2 bg-navy-950 border border-navy-800 rounded-xl text-xs text-white"></div>
            <div class="flex justify-end gap-2"><a href="{{ url_for('suppliers') }}" class="px-4 py-2 bg-navy-800 text-xs rounded-xl">İptal</a><button type="submit" class="px-4 py-2 bg-blue-600 text-xs rounded-xl">Güncelle</button></div>
        </form>
    </div>
    """, active_page='suppliers', s=s)

@app.route('/suppliers/detail/<int:id>')
@login_required
def supplier_detail(id):
    s = Supplier.query.get_or_404(id)
    return redirect(url_for('suppliers'))

@app.route('/suppliers/delete/<int:id>')
@editor_or_admin_required
def delete_supplier(id):
    s = Supplier.query.get_or_404(id)
    db.session.delete(s)
    db.session.commit()
    flash("Firma silindi.", "success")
    return redirect(url_for('suppliers'))

@app.route('/materials')
@login_required
def materials():
    materials_list = RawMaterial.query.order_by(RawMaterial.id.desc()).all()
    return render_page("""
    <div class="bg-navy-900 border border-navy-800 p-6 rounded-2xl">
        <h1 class="text-lg font-bold text-white mb-4">Hammadde Yönetimi</h1>
        <p class="text-xs text-slate-400">Hammadde listesi yükleniyor...</p>
    </div>
    """, active_page='materials')

@app.route('/prices')
@login_required
def prices():
    return render_page("""
    <div class="bg-navy-900 border border-navy-800 p-6 rounded-2xl">
        <h1 class="text-lg font-bold text-white mb-4">Fiyatlar & Karşılaştırma</h1>
        <p class="text-xs text-slate-400">Fiyat analizleri...</p>
    </div>
    """, active_page='prices')

@app.route('/categories')
@editor_or_admin_required
def categories_view():
    cats = Category.query.all()
    return render_page("""
    <div class="bg-navy-900 border border-navy-800 p-6 rounded-2xl">
        <h1 class="text-lg font-bold text-white mb-4">Kategoriler</h1>
    </div>
    """, active_page='categories')

@app.route('/logs')
@editor_or_admin_required
def logs():
    return render_page("""
    <div class="bg-navy-900 border border-navy-800 p-6 rounded-2xl">
        <h1 class="text-lg font-bold text-white mb-4">İşlem Geçmişi</h1>
    </div>
    """, active_page='logs')

@app.route('/admin/users')
@admin_required
def admin_users():
    return render_page("""
    <div class="bg-navy-900 border border-navy-800 p-6 rounded-2xl">
        <h1 class="text-lg font-bold text-white mb-4">Kullanıcı Yönetimi</h1>
    </div>
    """, active_page='users')

@app.route('/logout')
def logout():
    session.clear()
    flash("Çıkış yapıldı.", "success")
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)
