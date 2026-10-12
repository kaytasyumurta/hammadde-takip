# app.py - Hammadde Fiyat ve Takip Sistemi (Pro & Kusursuz Tasarım)
from datetime import datetime
from functools import wraps
import os
from flask import (
    Flask,
    flash,
    redirect,
    render_template_string,
    request,
    session,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
import sqlalchemy as sa
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "hammadde_takip_gizli_anahtar_2026")

db_url = os.environ.get("DATABASE_URL", "sqlite:///hammadde_sistemi.db")
if db_url and db_url.startswith("postgres://"):
  db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# --- VERİTABANI MODELLERİ ---
class User(db.Model):
  __tablename__ = "users"
  id = db.Column(db.Integer, primary_key=True)
  username = db.Column(db.String(80), unique=True, nullable=False)
  email = db.Column(db.String(120), unique=True, nullable=False)
  password_hash = db.Column(db.String(255), nullable=False)
  role = db.Column(db.String(20), nullable=False, default="personel")
  status = db.Column(db.String(20), nullable=False, default="pending")
  created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AuditLog(db.Model):
  __tablename__ = "audit_logs"
  id = db.Column(db.Integer, primary_key=True)
  user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
  action = db.Column(db.String(50), nullable=False)
  details = db.Column(db.Text)
  timestamp = db.Column(db.DateTime, default=datetime.utcnow)


class Category(db.Model):
  __tablename__ = "categories"
  id = db.Column(db.Integer, primary_key=True)
  name = db.Column(db.String(100), unique=True, nullable=False)


class RawMaterial(db.Model):
  __tablename__ = "raw_materials"
  id = db.Column(db.Integer, primary_key=True)
  code = db.Column(db.String(50), unique=True, nullable=False)
  name = db.Column(db.String(150), nullable=False)
  category_id = db.Column(db.Integer, db.ForeignKey("categories.id"))
  unit = db.Column(db.String(20), nullable=False)
  description = db.Column(db.Text)
  status = db.Column(db.String(20), nullable=False, default="active")
  created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
  updated_at = db.Column(
      db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
  )

  category = db.relationship("Category", backref="materials")
  creator = db.relationship("User", backref="materials")


class Supplier(db.Model):
  __tablename__ = "suppliers"
  id = db.Column(db.Integer, primary_key=True)
  name = db.Column(db.String(150), nullable=False)
  contact_person = db.Column(db.String(100))
  phone = db.Column(db.String(50))
  email = db.Column(db.String(120))
  address = db.Column(db.Text)
  city = db.Column(db.String(50))
  tax_no = db.Column(db.String(50))
  notes = db.Column(db.Text)
  status = db.Column(db.String(20), nullable=False, default="active")
  created_by = db.Column(db.Integer, db.ForeignKey("users.id"))

  creator = db.relationship("User", backref="suppliers")


class Price(db.Model):
  __tablename__ = "prices"
  id = db.Column(db.Integer, primary_key=True)
  material_id = db.Column(
      db.Integer, db.ForeignKey("raw_materials.id"), nullable=False
  )
  supplier_id = db.Column(
      db.Integer, db.ForeignKey("suppliers.id"), nullable=False
  )
  date = db.Column(db.String(20), nullable=False)
  currency = db.Column(db.String(10), nullable=False, default="TL")
  unit_price = db.Column(db.Float, nullable=False)
  shipping_status = db.Column(
      db.String(30), nullable=False, default="included"
  )
  shipping_cost = db.Column(db.Float, default=0)
  shipping_excluded = db.Column(db.Float, nullable=False)
  shipping_included = db.Column(db.Float, nullable=False)
  valid_until = db.Column(db.String(20))
  notes = db.Column(db.Text)
  created_by = db.Column(db.Integer, db.ForeignKey("users.id"))

  material = db.relationship("RawMaterial", backref="prices")
  supplier = db.relationship("Supplier", backref="prices")


# --- OTOMATİK VERİTABANI KONTROLÜ ---
with app.app_context():
  db.create_all()
  inspector = sa.inspect(db.engine)
  if "prices" in inspector.get_table_names():
    columns = [c["name"] for c in inspector.get_columns("prices")]
    with db.engine.connect() as conn:
      if "shipping_status" not in columns:
        conn.execute(
            sa.text(
                "ALTER TABLE prices ADD COLUMN shipping_status VARCHAR(30)"
                " DEFAULT 'included'"
            )
        )
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
    if "user_id" not in session:
      flash("Lütfen önce giriş yapın.", "error")
      return redirect(url_for("login"))
    return f(*args, **kwargs)

  return decorated


def admin_required(f):
  @wraps(f)
  def decorated(*args, **kwargs):
    if "user_id" not in session or session.get("role") != "admin":
      flash("Bu işlem için Admin yetkisi gerekiyor.", "error")
      return redirect(url_for("index"))
    return f(*args, **kwargs)

  return decorated


def editor_or_admin_required(f):
  @wraps(f)
  def decorated(*args, **kwargs):
    if "user_id" not in session or session.get("role") not in [
        "admin",
        "yonetici",
    ]:
      flash("Bu işlem için Yönetici veya Admin yetkisi gerekiyor.", "error")
      return redirect(url_for("index"))
    return f(*args, **kwargs)

  return decorated


def tr_format(value):
  if value is None:
    return ""
  try:
    val = float(value)
    return (
        f"{val:,.2f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )
  except:
    return str(value)


app.jinja_env.filters["tr_num"] = tr_format

# --- PRO & KUSURSUZ ŞABLON YAPISI ---
BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="tr" x-data="{ darkMode: localStorage.getItem('darkMode') === 'true' }" :class="{ 'dark': darkMode }">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hammadde Fiyat ve Takip Sistemi</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>tailwind.config = { darkMode: 'class', theme: { extend: {} } }</script>
    <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>body { font-family: 'Plus Jakarta Sans', sans-serif; }</style>
</head>
<body class="bg-slate-100 dark:bg-slate-950 text-slate-800 dark:text-slate-100 min-h-screen flex flex-col transition-colors duration-300">
    <!-- PRO NAVBAR -->
    <nav class="bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 shadow-sm sticky top-0 z-50">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="flex justify-between h-20 items-center">
                <!-- Sol: Logo -->
                <div class="flex items-center gap-3">
                    <a href="{{ url_for('index') }}" class="flex items-center gap-3 group">
                        <div class="w-11 h-11 rounded-2xl bg-gradient-to-tr from-blue-600 to-indigo-600 flex items-center justify-center text-white shadow-lg shadow-blue-500/25 group-hover:scale-105 transition-transform">
                            <i class="fa-solid fa-cubes text-lg"></i>
                        </div>
                        <div>
                            <span class="font-bold text-lg tracking-tight">Hammadde Pro</span>
                            <span class="block text-[10px] text-slate-400 font-semibold uppercase tracking-wider">Tedarik & Fiyat Takip</span>
                        </div>
                    </a>
                </div>

                <!-- Sağ: Menü Sekmeleri ve Pro Kullanıcı Alanı -->
                <div class="flex items-center gap-4">
                    {% if session.get('user_id') and session.get('status') == 'active' %}
                    <div class="hidden xl:flex items-center gap-1 bg-slate-100 dark:bg-slate-800 p-1.5 rounded-2xl border border-slate-200 dark:border-slate-700">
                        <a href="{{ url_for('materials') }}" class="px-3.5 py-2 rounded-xl text-sm font-medium hover:bg-white dark:hover:bg-slate-700 shadow-sm transition-all">Hammaddeler</a>
                        <a href="{{ url_for('suppliers') }}" class="px-3.5 py-2 rounded-xl text-sm font-medium hover:bg-white dark:hover:bg-slate-700 shadow-sm transition-all">Firmalar</a>
                        <a href="{{ url_for('prices') }}" class="px-3.5 py-2 rounded-xl text-sm font-medium hover:bg-white dark:hover:bg-slate-700 shadow-sm transition-all">Fiyatlar & Karşılaştırma</a>
                        {% if session.get('role') in ['admin', 'yonetici'] %}
                        <a href="{{ url_for('categories_view') }}" class="px-3.5 py-2 rounded-xl text-sm font-medium hover:bg-white dark:hover:bg-slate-700 shadow-sm transition-all">Kategoriler</a>
                        <a href="{{ url_for('logs') }}" class="px-3.5 py-2 rounded-xl text-sm font-medium hover:bg-white dark:hover:bg-slate-700 shadow-sm transition-all">Loglar</a>
                        {% endif %}
                        {% if session.get('role') == 'admin' %}
                        <a href="{{ url_for('admin_users') }}" class="px-3.5 py-2 rounded-xl text-sm font-medium text-amber-600 dark:text-amber-400 hover:bg-white dark:hover:bg-slate-700 shadow-sm transition-all">Kullanıcılar</a>
                        {% endif %}
                    </div>
                    {% endif %}

                    <!-- Dark Mode Toggle -->
                    <button @click="darkMode = !darkMode; localStorage.setItem('darkMode', darkMode)" class="w-10 h-10 rounded-2xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center hover:scale-105 transition-transform border border-slate-200 dark:border-slate-700">
                        <i class="fa-solid" :class="darkMode ? 'fa-sun text-amber-400' : 'fa-moon text-slate-600'"></i>
                    </button>

                    <!-- Pro Kullanıcı Kartı & Çıkış -->
                    {% if session.get('user_id') %}
                        <div class="flex items-center gap-3 pl-3 border-l border-slate-200 dark:border-slate-800">
                            <div class="flex items-center gap-2.5 bg-slate-50 dark:bg-slate-800 py-1.5 px-3.5 rounded-2xl border border-slate-200 dark:border-slate-700 shadow-sm">
                                <div class="w-8 h-8 rounded-xl bg-blue-500/10 text-blue-600 dark:text-blue-400 font-bold flex items-center justify-center text-xs uppercase">
                                    {{ session.get('username')[:2] }}
                                </div>
                                <div class="hidden sm:block text-left leading-tight">
                                    <div class="text-xs font-bold">{{ session.get('username') }}</div>
                                    <span class="text-[9px] px-1.5 py-0.5 rounded font-bold uppercase tracking-wider {{ 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300' if session.get('role')=='admin' else 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300' }}">
                                        {{ session.get('role') }}
                                    </span>
                                </div>
                            </div>
                            <a href="{{ url_for('logout') }}" title="Çıkış Yap" class="w-10 h-10 rounded-2xl bg-rose-50 dark:bg-rose-950/40 text-rose-600 dark:text-rose-400 flex items-center justify-center hover:bg-rose-600 hover:text-white transition-all shadow-sm border border-rose-100 dark:border-rose-900/50">
                                <i class="fa-solid fa-power-off text-sm"></i>
                            </a>
                        </div>
                    {% else %}
                        <div class="flex items-center gap-2">
                            <a href="{{ url_for('login') }}" class="px-4 py-2.5 text-sm font-semibold hover:text-blue-600 transition-colors">Giriş Yap</a>
                            <a href="{{ url_for('register') }}" class="px-5 py-2.5 text-sm font-semibold bg-blue-600 text-white rounded-2xl hover:bg-blue-700 shadow-lg shadow-blue-600/20 transition-all">Kayıt Ol</a>
                        </div>
                    {% endif %}
                </div>
            </div>
        </div>
    </nav>

    <!-- FLASH MESSAGES -->
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-6 w-full">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="p-4 mb-4 rounded-2xl text-sm font-medium border flex items-center gap-3 shadow-sm {{ 'bg-emerald-50 border-emerald-200 text-emerald-800 dark:bg-emerald-950/50 dark:border-emerald-800 dark:text-emerald-300' if category == 'success' else 'bg-rose-50 border-rose-200 text-rose-800 dark:bg-rose-950/50 dark:border-rose-800 dark:text-rose-300' }}">
                        <i class="fa-solid {{ 'fa-circle-check text-emerald-500' if category == 'success' else 'fa-circle-exclamation text-rose-500' }} text-lg"></i>
                        <span>{{ message }}</span>
                    </div>
                {% endfor %}
            {% endif %}
        {% endwith %}
    </div>

    <!-- MAIN CONTENT -->
    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 flex-grow w-full space-y-6">
        CONTENT_PLACEHOLDER
    </main>

    <!-- FOOTER -->
    <footer class="bg-white dark:bg-slate-900 border-t border-slate-200 dark:border-slate-800 py-6 text-center text-xs text-slate-500">
        Hammadde Fiyat ve Takip Sistemi &copy; 2026 | Profesyonel Bulut Altyapısı
    </footer>
</body>
</html>
"""


def render_page(content_html, **kwargs):
  full_html = BASE_TEMPLATE.replace("CONTENT_PLACEHOLDER", content_html)
  return render_template_string(full_html, **kwargs)


@app.route("/")
def index():
  if "user_id" not in session:
    return render_page("""
        <div class="max-w-2xl mx-auto text-center py-20 space-y-6">
            <div class="inline-flex p-3 rounded-2xl bg-blue-500/10 text-blue-600 dark:text-blue-400 mb-2">
                <i class="fa-solid fa-chart-line text-4xl"></i>
            </div>
            <h1 class="text-4xl sm:text-5xl font-extrabold tracking-tight">Hammadde ve Tedarik Takip Platformu</h1>
            <p class="text-slate-600 dark:text-slate-400 text-lg max-w-xl mx-auto">Gelişmiş bulut altyapısı ile hammadde fiyatlarını, tedarikçileri ve nakliye maliyetlerini profesyonelce yönetin.</p>
            <div class="flex justify-center gap-4 pt-4">
                <a href="%s" class="px-8 py-3.5 bg-blue-600 text-white font-semibold rounded-2xl shadow-lg shadow-blue-600/25 hover:bg-blue-700 transition-all">Giriş Yap</a>
                <a href="%s" class="px-8 py-3.5 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 font-semibold rounded-2xl hover:bg-slate-50 dark:hover:bg-slate-700 transition-all">Kayıt Ol</a>
            </div>
        </div>
        """ % (url_for('login'), url_for('register')))

  if session.get("status") == "pending":
    return render_page("""
        <div class="max-w-md mx-auto text-center py-20 bg-white dark:bg-slate-900 p-8 rounded-3xl shadow-xl border border-slate-200 dark:border-slate-800 space-y-4">
            <div class="w-16 h-16 bg-amber-500/10 text-amber-500 rounded-2xl flex items-center justify-center mx-auto text-2xl">
                <i class="fa-solid fa-clock-rotate-left"></i>
            </div>
            <h2 class="text-2xl font-bold">Hesabınız Onay Bekliyor</h2>
            <p class="text-slate-600 dark:text-slate-400 text-sm">Yönetici onayından sonra tüm modüllere tam erişim sağlayabileceksiniz.</p>
            <a href="%s" class="inline-block px-6 py-2.5 bg-slate-200 dark:bg-slate-800 rounded-xl text-sm font-semibold hover:bg-slate-300 transition-all">Çıkış Yap</a>
        </div>
        """ % url_for('logout'))

  m_count = RawMaterial.query.count()
  s_count = Supplier.query.count()
  p_count = Price.query.count()

  return render_page(
      """
    <div class="space-y-6">
        <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 bg-white dark:bg-slate-900 p-6 rounded-3xl border border-slate-200 dark:border-slate-800 shadow-sm">
            <div>
                <h1 class="text-2xl font-bold">Kontrol Paneli</h1>
                <p class="text-sm text-slate-500 mt-1">Sisteme hoş geldiniz, <span class="font-semibold text-blue-600 dark:text-blue-400">{{ session.get('username') }}</span></p>
            </div>
            <div>
                <a href="{{ url_for('prices') }}" class="px-5 py-2.5 bg-blue-600 text-white rounded-2xl text-sm font-semibold shadow-lg shadow-blue-600/20 hover:bg-blue-700 transition-all inline-flex items-center gap-2"><i class="fa-solid fa-tags"></i> Fiyat Karşılaştır</a>
            </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div class="bg-white dark:bg-slate-900 p-6 rounded-3xl border border-slate-200 dark:border-slate-800 shadow-sm flex items-center justify-between">
                <div><p class="text-sm font-medium text-slate-500">Toplam Hammadde</p><p class="text-3xl font-extrabold mt-1 text-blue-600">{{ m_count }}</p></div>
                <div class="w-14 h-14 bg-blue-50 dark:bg-blue-950/50 text-blue-600 rounded-2xl flex items-center justify-center text-xl"><i class="fa-solid fa-cubes"></i></div>
            </div>
            <div class="bg-white dark:bg-slate-900 p-6 rounded-3xl border border-slate-200 dark:border-slate-800 shadow-sm flex items-center justify-between">
                <div><p class="text-sm font-medium text-slate-500">Kayıtlı Tedarikçiler</p><p class="text-3xl font-extrabold mt-1 text-emerald-600">{{ s_count }}</p></div>
                <div class="w-14 h-14 bg-emerald-50 dark:bg-emerald-950/50 text-emerald-600 rounded-2xl flex items-center justify-center text-xl"><i class="fa-solid fa-truck-fast"></i></div>
            </div>
            <div class="bg-white dark:bg-slate-900 p-6 rounded-3xl border border-slate-200 dark:border-slate-800 shadow-sm flex items-center justify-between">
                <div><p class="text-sm font-medium text-slate-500">Fiyat Kayıtları</p><p class="text-3xl font-extrabold mt-1 text-amber-600">{{ p_count }}</p></div>
                <div class="w-14 h-14 bg-amber-50 dark:bg-amber-950/50 text-amber-600 rounded-2xl flex items-center justify-center text-xl"><i class="fa-solid fa-tag"></i></div>
            </div>
        </div>

        <div class="bg-white dark:bg-slate-900 p-8 rounded-3xl border border-slate-200 dark:border-slate-800 shadow-sm space-y-4">
            <h3 class="text-lg font-bold">Hızlı Erişim Menüsü</h3>
            <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <a href="{{ url_for('materials') }}" class="p-5 rounded-2xl border border-slate-200 dark:border-slate-800 hover:border-blue-500/50 hover:bg-blue-50/50 dark:hover:bg-slate-800/50 transition-all group">
                    <div class="text-blue-600 text-lg mb-2"><i class="fa-solid fa-box-open"></i></div>
                    <div class="font-bold group-hover:text-blue-600 transition-colors">Hammaddeleri Yönet</div>
                    <div class="text-xs text-slate-500 mt-1">Hammadde ekle, düzenle ve listele.</div>
                </a>
                <a href="{{ url_for('suppliers') }}" class="p-5 rounded-2xl border border-slate-200 dark:border-slate-800 hover:border-emerald-500/50 hover:bg-emerald-50/50 dark:hover:bg-slate-800/50 transition-all group">
                    <div class="text-emerald-600 text-lg mb-2"><i class="fa-solid fa-building"></i></div>
                    <div class="font-bold group-hover:text-emerald-600 transition-colors">Firmaları Yönet</div>
                    <div class="text-xs text-slate-500 mt-1">Tedarikçi firma ve iletişim bilgileri.</div>
                </a>
                <a href="{{ url_for('prices') }}" class="p-5 rounded-2xl border border-slate-200 dark:border-slate-800 hover:border-indigo-500/50 hover:bg-indigo-50/50 dark:hover:bg-slate-800/50 transition-all group">
                    <div class="text-indigo-600 text-lg mb-2"><i class="fa-solid fa-scale-balanced"></i></div>
                    <div class="font-bold group-hover:text-indigo-600 transition-colors">Fiyat Karşılaştırma</div>
                    <div class="text-xs text-slate-500 mt-1">En uygun tedarikçi analizleri.</div>
                </a>
            </div>
        </div>
    </div>
    """,
      m_count=m_count,
      s_count=s_count,
      p_count=p_count,
  )


@app.route("/register", methods=["GET", "POST"])
def register():
  if request.method == "POST":
    username = request.form.get("username").strip()
    email = request.form.get("email").strip()
    password = request.form.get("password")

    user_count = User.query.count()
    role = "admin" if user_count == 0 else "personel"
    status = "active" if user_count == 0 else "pending"

    try:
      pwd_hash = generate_password_hash(password)
      new_user = User(
          username=username,
          email=email,
          password_hash=pwd_hash,
          role=role,
          status=status,
      )
      db.session.add(new_user)
      db.session.commit()
      if user_count == 0:
        flash(
            "İlk kayıt olduğunuz için Admin olarak atandınız ve giriş"
            " yapabilirsiniz.",
            "success",
        )
      else:
        flash(
            "Kayıt başarılı. Hesabınız yönetici onayından sonra aktif"
            " edilecektir.",
            "success",
        )
      return redirect(url_for("login"))
    except:
      db.session.rollback()
      flash("Bu kullanıcı adı veya e-posta zaten kullanımda.", "error")

  return render_page("""
    <div class="max-w-md mx-auto bg-white dark:bg-slate-900 p-8 rounded-3xl shadow-xl border border-slate-200 dark:border-slate-800">
        <h2 class="text-2xl font-bold mb-6 text-center">Hesap Oluştur</h2>
        <form method="POST" class="space-y-4">
            <div><label class="block text-sm font-semibold mb-1.5">Kullanıcı Adı</label><input type="text" name="username" required class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></div>
            <div><label class="block text-sm font-semibold mb-1.5">E-posta</label><input type="email" name="email" required class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></div>
            <div><label class="block text-sm font-semibold mb-1.5">Şifre</label><input type="password" name="password" required class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></div>
            <button type="submit" class="w-full py-3.5 bg-blue-600 text-white font-semibold rounded-xl shadow-lg shadow-blue-600/20 hover:bg-blue-700 transition-all mt-2">Kayıt Ol</button>
        </form>
    </div>
    """)


@app.route("/login", methods=["GET", "POST"])
def login():
  if request.method == "POST":
    username = request.form.get("username").strip()
    password = request.form.get("password")
    user = User.query.filter_by(username=username).first()

    if user and check_password_hash(user.password_hash, password):
      session["user_id"] = user.id
      session["username"] = user.username
      session["role"] = user.role
      session["status"] = user.status
      log_action(user.id, "LOGIN", f"Kullanıcı giriş yaptı: {username}")
      flash("Başarıyla giriş yaptınız.", "success")
      return redirect(url_for("index"))
    else:
      flash("Geçersiz kullanıcı adı veya şifre.", "error")

  return render_page("""
    <div class="max-w-md mx-auto bg-white dark:bg-slate-900 p-8 rounded-3xl shadow-xl border border-slate-200 dark:border-slate-800">
        <h2 class="text-2xl font-bold mb-6 text-center">Giriş Yap</h2>
        <form method="POST" class="space-y-4">
            <div><label class="block text-sm font-semibold mb-1.5">Kullanıcı Adı</label><input type="text" name="username" required class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></div>
            <div><label class="block text-sm font-semibold mb-1.5">Şifre</label><input type="password" name="password" required class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></div>
            <button type="submit" class="w-full py-3.5 bg-blue-600 text-white font-semibold rounded-xl shadow-lg shadow-blue-600/20 hover:bg-blue-700 transition-all mt-2">Giriş Yap</button>
        </form>
    </div>
    """)


@app.route("/logout")
def logout():
  if "user_id" in session:
    log_action(session["user_id"], "LOGOUT", "Kullanıcı çıkış yaptı")
  session.clear()
  flash("Çıkış yapıldı.", "success")
  return redirect(url_for("login"))


# --- KATEGORİ YÖNETİMİ ---
@app.route("/categories")
@editor_or_admin_required
def categories_view():
  cats = Category.query.order_by(Category.name).all()
  return render_page(
      """
    <div class="space-y-6" x-data="{ openAdd: false }">
        <div class="flex justify-between items-center bg-white dark:bg-slate-900 p-6 rounded-3xl border border-slate-200 dark:border-slate-800 shadow-sm">
            <div><h1 class="text-2xl font-bold">Kategori Yönetimi</h1><p class="text-sm text-slate-500 mt-1">Hammadde kategorilerini kolayca ekleyin ve yönetin.</p></div>
            <button @click="openAdd = true" class="px-5 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-semibold shadow-lg shadow-blue-600/20 hover:bg-blue-700 transition-all inline-flex items-center gap-2"><i class="fa-solid fa-plus"></i> Yeni Kategori</button>
        </div>
        <div class="bg-white dark:bg-slate-900 rounded-3xl border border-slate-200 dark:border-slate-800 overflow-hidden shadow-sm max-w-3xl">
            <table class="w-full text-left border-collapse">
                <thead>
                    <tr class="bg-slate-100 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 text-xs font-bold text-slate-600 dark:text-slate-300 uppercase">
                        <th class="p-4.5">Kategori Adı</th>
                        <th class="p-4.5 text-right">İşlemler</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-slate-200 dark:divide-slate-800 text-sm">
                    {% for c in categories %}
                    <tr class="hover:bg-slate-50/50 dark:hover:bg-slate-800/40 transition-colors">
                        <td class="p-4.5 font-semibold">{{ c.name }}</td>
                        <td class="p-4.5 text-right space-x-3">
                            <a href="{{ url_for('edit_category', id=c.id) }}" class="text-blue-600 dark:text-blue-400 font-semibold hover:underline">Düzenle</a>
                            <a href="{{ url_for('delete_category', id=c.id) }}" onclick="return confirm('Bu kategoriyi silmek istediğinizden emin misiniz?')" class="text-rose-600 dark:text-rose-400 font-semibold hover:underline">Sil</a>
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="2" class="p-8 text-center text-slate-500">Kategori bulunamadı.</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        <div x-show="openAdd" class="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50" style="display: none;">
            <div class="bg-white dark:bg-slate-900 p-8 rounded-3xl max-w-md w-full shadow-2xl border border-slate-200 dark:border-slate-800 space-y-4" @click.outside="openAdd = false">
                <h3 class="text-xl font-bold">Yeni Kategori Ekle</h3>
                <form action="{{ url_for('add_category') }}" method="POST" class="space-y-4">
                    <div><label class="block text-sm font-semibold mb-1.5">Kategori Adı</label><input type="text" name="name" required class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></div>
                    <div class="flex justify-end gap-2 pt-2"><button type="button" @click="openAdd = false" class="px-5 py-2.5 bg-slate-200 dark:bg-slate-800 rounded-xl text-sm font-semibold">İptal</button><button type="submit" class="px-5 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-semibold hover:bg-blue-700">Kaydet</button></div>
                </form>
            </div>
        </div>
    </div>
    """,
      categories=cats,
  )


@app.route("/categories/add", methods=["POST"])
@editor_or_admin_required
def add_category():
  name = request.form.get("name", "").strip()
  if name:
    try:
      db.session.add(Category(name=name))
      db.session.commit()
      log_action(session["user_id"], "ADD_CATEGORY", f"Kategori eklendi: {name}")
      flash("Kategori başarıyla eklendi.", "success")
    except:
      db.session.rollback()
      flash("Bu kategori adı zaten mevcut.", "error")
  return redirect(url_for("categories_view"))


@app.route("/categories/edit/<int:id>", methods=["GET", "POST"])
@editor_or_admin_required
def edit_category(id):
  cat = Category.query.get_or_404(id)
  if request.method == "POST":
    cat.name = request.form.get("name", "").strip()
    try:
      db.session.commit()
      log_action(
          session["user_id"], "EDIT_CATEGORY", f"Kategori güncellendi: {id}"
      )
      flash("Kategori güncellendi.", "success")
      return redirect(url_for("categories_view"))
    except:
      db.session.rollback()
      flash("Bu kategori adı başka bir kayıtta var.", "error")

  return render_page(
      """
    <div class="max-w-md mx-auto bg-white dark:bg-slate-900 p-8 rounded-3xl shadow-xl border border-slate-200 dark:border-slate-800 space-y-4">
        <h2 class="text-2xl font-bold">Kategori Düzenle</h2>
        <form method="POST" class="space-y-4">
            <div><label class="block text-sm font-semibold mb-1.5">Kategori Adı</label><input type="text" name="name" value="{{ cat.name }}" required class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></div>
            <div class="flex justify-end gap-2 pt-2"><a href="{{ url_for('categories_view') }}" class="px-5 py-2.5 bg-slate-200 dark:bg-slate-800 rounded-xl text-sm font-semibold">İptal</a><button type="submit" class="px-5 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-semibold hover:bg-blue-700">Güncelle</button></div>
        </form>
    </div>
    """,
      cat=cat,
  )


@app.route("/categories/delete/<int:id>")
@editor_or_admin_required
def delete_category(id):
  cat = Category.query.get_or_404(id)
  if cat.materials:
    flash(
        "Bu kategoriye bağlı hammaddeler bulunduğu için silinemez.", "error"
    )
  else:
    db.session.delete(cat)
    db.session.commit()
    log_action(session["user_id"], "DELETE_CATEGORY", f"Kategori silindi: {id}")
    flash("Kategori silindi.", "success")
  return redirect(url_for("categories_view"))


@app.route("/admin/users")
@admin_required
def admin_users():
  users = User.query.order_by(User.id.desc()).all()
  return render_page(
      """
    <div class="space-y-6">
        <div class="bg-white dark:bg-slate-900 p-6 rounded-3xl border border-slate-200 dark:border-slate-800 shadow-sm">
            <h1 class="text-2xl font-bold">Kullanıcı Yönetimi</h1>
            <p class="text-sm text-slate-500 mt-1">Sistem kullanıcı yetkilerini ve hesap durumlarını yönetin.</p>
        </div>
        <div class="bg-white dark:bg-slate-900 rounded-3xl border border-slate-200 dark:border-slate-800 overflow-hidden shadow-sm">
            <table class="w-full text-left border-collapse">
                <thead>
                    <tr class="bg-slate-100 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 text-xs font-bold text-slate-600 dark:text-slate-300 uppercase">
                        <th class="p-4.5">Kullanıcı Adı</th>
                        <th class="p-4.5">E-posta</th>
                        <th class="p-4.5">Rol</th>
                        <th class="p-4.5">Durum</th>
                        <th class="p-4.5 text-right">İşlem</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-slate-200 dark:divide-slate-800 text-sm">
                    {% for u in users %}
                    <tr class="hover:bg-slate-50/50 dark:hover:bg-slate-800/40 transition-colors">
                        <td class="p-4.5 font-semibold">{{ u.username }}</td>
                        <td class="p-4.5 text-slate-500">{{ u.email }}</td>
                        <td class="p-4.5">
                            <form action="{{ url_for('admin_update_user', user_id=u.id) }}" method="POST" class="flex items-center gap-2">
                                <select name="role" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-xs font-semibold">
                                    <option value="admin" {{ 'selected' if u.role=='admin' }}>Admin</option>
                                    <option value="yonetici" {{ 'selected' if u.role=='yonetici' }}>Yönetici</option>
                                    <option value="personel" {{ 'selected' if u.role=='personel' }}>Personel</option>
                                    <option value="goruntuleyen" {{ 'selected' if u.role=='goruntuleyen' }}>Görüntüleyen</option>
                                </select>
                        </td>
                        <td class="p-4.5">
                                <select name="status" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-xs font-semibold">
                                    <option value="active" {{ 'selected' if u.status=='active' }}>Aktif</option>
                                    <option value="pending" {{ 'selected' if u.status=='pending' }}>Onay Bekliyor</option>
                                    <option value="passive" {{ 'selected' if u.status=='passive' }}>Pasif</option>
                                </select>
                        </td>
                        <td class="p-4.5 text-right"><button type="submit" class="px-4 py-2 bg-blue-600 text-white rounded-xl text-xs font-semibold shadow-sm hover:bg-blue-700 transition-all">Güncelle</button></form></td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    """,
      users=users,
  )


@app.route("/admin/users/<int:user_id>/update", methods=["POST"])
@admin_required
def admin_update_user(user_id):
  u = User.query.get_or_404(user_id)
  u.role = request.form.get("role")
  u.status = request.form.get("status")
  db.session.commit()
  log_action(
      session["user_id"],
      "UPDATE_USER",
      f"Kullanıcı ID {user_id} güncellendi: Rol={u.role}, Durum={u.status}",
  )
  flash("Kullanıcı güncellendi.", "success")
  return redirect(url_for("admin_users"))


@app.route("/logs")
@editor_or_admin_required
def logs():
  all_logs = (
      db.session.query(AuditLog, User)
      .outerjoin(User, AuditLog.user_id == User.id)
      .order_by(AuditLog.id.desc())
      .limit(100)
      .all()
  )
  return render_page(
      """
    <div class="space-y-6">
        <div class="bg-white dark:bg-slate-900 p-6 rounded-3xl border border-slate-200 dark:border-slate-800 shadow-sm">
            <h1 class="text-2xl font-bold">İşlem Geçmişi (Loglar)</h1>
            <p class="text-sm text-slate-500 mt-1">Sistem üzerinde gerçekleştirilen tüm kritik işlemlerin denetim kaydı.</p>
        </div>
        <div class="bg-white dark:bg-slate-900 rounded-3xl border border-slate-200 dark:border-slate-800 overflow-hidden shadow-sm">
            <table class="w-full text-left border-collapse">
                <thead>
                    <tr class="bg-slate-100 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 text-xs font-bold text-slate-600 dark:text-slate-300 uppercase">
                        <th class="p-4.5">Tarih</th>
                        <th class="p-4.5">Kullanıcı</th>
                        <th class="p-4.5">İşlem</th>
                        <th class="p-4.5">Detay</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-slate-200 dark:divide-slate-800 text-sm">
                    {% for l, u in logs %}
                    <tr class="hover:bg-slate-50/50 dark:hover:bg-slate-800/40 transition-colors">
                        <td class="p-4.5 text-slate-400 text-xs font-mono">{{ l.timestamp.strftime('%Y-%m-%d %H:%M:%S') }}</td>
                        <td class="p-4.5 font-semibold">{{ u.username if u else 'Sistem' }}</td>
                        <td class="p-4.5"><span class="px-2.5 py-1 rounded-lg bg-slate-100 dark:bg-slate-800 text-xs font-mono font-bold text-blue-600 dark:text-blue-400">{{ l.action }}</span></td>
                        <td class="p-4.5 text-slate-600 dark:text-slate-300">{{ l.details }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    """,
      logs=all_logs,
  )


@app.route("/materials")
@login_required
def materials():
  if session.get("status") != "active":
    return redirect(url_for("index"))

  search = request.args.get("search", "")
  cat_filter = request.args.get("category", "")

  query = RawMaterial.query
  if search:
    query = query.filter(
        db.or_(
            RawMaterial.name.ilike(f"%{search}%"),
            RawMaterial.code.ilike(f"%{search}%"),
        )
    )
  if cat_filter:
    query = query.filter_by(category_id=int(cat_filter))

  materials_list = query.order_by(RawMaterial.id.desc()).all()
  categories = Category.query.order_by(Category.name).all()

  return render_page(
      """
    <div class="space-y-6" x-data="{ openAdd: false }">
        <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 bg-white dark:bg-slate-900 p-6 rounded-3xl border border-slate-200 dark:border-slate-800 shadow-sm">
            <div><h1 class="text-2xl font-bold">Hammadde Yönetimi</h1><p class="text-sm text-slate-500 mt-1">Tüm hammadde envanterini takip edin.</p></div>
            <button @click="openAdd = true" class="px-5 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-semibold shadow-lg shadow-blue-600/20 hover:bg-blue-700 transition-all inline-flex items-center gap-2"><i class="fa-solid fa-plus"></i> Yeni Hammadde</button>
        </div>

        <form method="GET" class="bg-white dark:bg-slate-900 p-4 rounded-3xl border border-slate-200 dark:border-slate-800 shadow-sm flex flex-wrap gap-4 items-center">
            <input type="text" name="search" value="{{ search_val }}" placeholder="Hammadde adı veya kodu..." class="px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm flex-grow outline-none">
            <select name="category" class="px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none">
                <option value="">Tüm Kategoriler</option>
                {% for c in categories %}
                <option value="{{ c.id }}" {{ 'selected' if cat_val == c.id|string }}>{{ c.name }}</option>
                {% endfor %}
            </select>
            <button type="submit" class="px-6 py-3 bg-slate-900 dark:bg-slate-800 text-white rounded-xl text-sm font-semibold hover:bg-slate-800">Filtrele</button>
            <a href="{{ url_for('materials') }}" class="px-6 py-3 bg-slate-100 dark:bg-slate-800 rounded-xl text-sm font-semibold hover:bg-slate-200">Sıfırla</a>
        </form>

        <div class="bg-white dark:bg-slate-900 rounded-3xl border border-slate-200 dark:border-slate-800 overflow-hidden shadow-sm">
            <table class="w-full text-left border-collapse">
                <thead>
                    <tr class="bg-slate-100 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 text-xs font-bold text-slate-600 dark:text-slate-300 uppercase">
                        <th class="p-4.5">Kod</th>
                        <th class="p-4.5">Adı</th>
                        <th class="p-4.5">Kategori</th>
                        <th class="p-4.5">Birim</th>
                        <th class="p-4.5">Durum</th>
                        <th class="p-4.5 text-right">İşlemler</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-slate-200 dark:divide-slate-800 text-sm">
                    {% for m in materials %}
                    <tr class="hover:bg-slate-50/50 dark:hover:bg-slate-800/40 transition-colors">
                        <td class="p-4.5 font-mono font-bold text-blue-600 dark:text-blue-400">{{ m.code }}</td>
                        <td class="p-4.5 font-semibold">{{ m.name }}</td>
                        <td class="p-4.5 text-slate-500">{{ m.category.name if m.category else '-' }}</td>
                        <td class="p-4.5 uppercase font-medium text-xs">{{ m.unit }}</td>
                        <td class="p-4.5"><span class="px-2.5 py-1 rounded-full text-xs font-bold {{ 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300' if m.status=='active' else 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300' }}">{{ 'Aktif' if m.status=='active' else 'Pasif' }}</span></td>
                        <td class="p-4.5 text-right space-x-3">
                            {% if session.get('role') in ['admin', 'yonetici'] or m.created_by == session.get('user_id') %}
                            <a href="{{ url_for('edit_material', id=m.id) }}" class="text-blue-600 dark:text-blue-400 font-semibold hover:underline">Düzenle</a>
                            {% endif %}
                            {% if session.get('role') in ['admin', 'yonetici'] %}
                            <a href="{{ url_for('delete_material', id=m.id) }}" onclick="return confirm('Silmek istediğinize emin misiniz?')" class="text-rose-600 dark:text-rose-400 font-semibold hover:underline">Sil</a>
                            {% endif %}
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="6" class="p-8 text-center text-slate-500">Hammadde kaydı bulunamadı.</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <div x-show="openAdd" class="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50" style="display: none;">
            <div class="bg-white dark:bg-slate-900 p-8 rounded-3xl max-w-lg w-full shadow-2xl border border-slate-200 dark:border-slate-800 space-y-4" @click.outside="openAdd = false">
                <h3 class="text-xl font-bold">Yeni Hammadde Ekle</h3>
                <form action="{{ url_for('add_material') }}" method="POST" class="space-y-4">
                    <div><label class="block text-sm font-semibold mb-1.5">Kod</label><input type="text" name="code" required class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></div>
                    <div><label class="block text-sm font-semibold mb-1.5">Adı</label><input type="text" name="name" required class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></div>
                    <div><label class="block text-sm font-semibold mb-1.5">Kategori</label><select name="category_id" class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none">{% for c in categories %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></div>
                    <div><label class="block text-sm font-semibold mb-1.5">Birim</label><select name="unit" class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"><option value="kg">kg</option><option value="ton">ton</option><option value="litre">litre</option><option value="adet">adet</option></select></div>
                    <div><label class="block text-sm font-semibold mb-1.5">Açıklama</label><textarea name="description" rows="2" class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></textarea></div>
                    <div class="flex justify-end gap-2 pt-2"><button type="button" @click="openAdd = false" class="px-5 py-2.5 bg-slate-200 dark:bg-slate-800 rounded-xl text-sm font-semibold">İptal</button><button type="submit" class="px-5 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-semibold hover:bg-blue-700">Kaydet</button></div>
                </form>
            </div>
        </div>
    </div>
    """,
      materials=materials_list,
      categories=categories,
      search_val=search,
      cat_val=cat_filter,
  )


@app.route("/materials/add", methods=["POST"])
@login_required
def add_material():
  if session.get("status") != "active":
    return redirect(url_for("index"))
  try:
    m = RawMaterial(
        code=request.form.get("code").strip(),
        name=request.form.get("name").strip(),
        category_id=request.form.get("category_id"),
        unit=request.form.get("unit"),
        description=request.form.get("description"),
        created_by=session.get("user_id"),
    )
    db.session.add(m)
    db.session.commit()
    log_action(session["user_id"], "ADD_MATERIAL", f"Hammadde eklendi: {m.code}")
    flash("Hammadde eklendi.", "success")
  except:
    db.session.rollback()
    flash("Bu hammadde kodu zaten mevcut.", "error")
  return redirect(url_for("materials"))


@app.route("/materials/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit_material(id):
  m = RawMaterial.query.get_or_404(id)
  if (
      session.get("role") not in ["admin", "yonetici"]
      and m.created_by != session.get("user_id")
  ):
    flash("Yetkiniz yok.", "error")
    return redirect(url_for("materials"))

  if request.method == "POST":
    m.code = request.form.get("code").strip()
    m.name = request.form.get("name").strip()
    m.category_id = request.form.get("category_id")
    m.unit = request.form.get("unit")
    m.description = request.form.get("description")
    m.status = request.form.get("status")
    db.session.commit()
    log_action(session["user_id"], "EDIT_MATERIAL", f"Hammadde güncellendi: {id}")
    flash("Güncellendi.", "success")
    return redirect(url_for("materials"))

  categories = Category.query.order_by(Category.name).all()
  return render_page(
      """
    <div class="max-w-lg mx-auto bg-white dark:bg-slate-900 p-8 rounded-3xl shadow-xl border border-slate-200 dark:border-slate-800 space-y-4">
        <h2 class="text-2xl font-bold">Hammadde Düzenle</h2>
        <form method="POST" class="space-y-4">
            <div><label class="block text-sm font-semibold mb-1.5">Kod</label><input type="text" name="code" value="{{ m.code }}" required class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></div>
            <div><label class="block text-sm font-semibold mb-1.5">Adı</label><input type="text" name="name" value="{{ m.name }}" required class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></div>
            <div><label class="block text-sm font-semibold mb-1.5">Kategori</label><select name="category_id" class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none">{% for c in categories %}<option value="{{ c.id }}" {{ 'selected' if m.category_id == c.id }}>{{ c.name }}</option>{% endfor %}</select></div>
            <div><label class="block text-sm font-semibold mb-1.5">Birim</label><select name="unit" class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none">{% for u in ['kg', 'ton', 'litre', 'adet'] %}<option value="{{ u }}" {{ 'selected' if m.unit == u }}>{{ u }}</option>{% endfor %}</select></div>
            <div><label class="block text-sm font-semibold mb-1.5">Açıklama</label><textarea name="description" rows="2" class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none">{{ m.description or '' }}</textarea></div>
            <div><label class="block text-sm font-semibold mb-1.5">Durum</label><select name="status" class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"><option value="active" {{ 'selected' if m.status == 'active' }}>Aktif</option><option value="passive" {{ 'selected' if m.status == 'passive' }}>Pasif</option></select></div>
            <div class="flex justify-end gap-2 pt-2"><a href="{{ url_for('materials') }}" class="px-5 py-2.5 bg-slate-200 dark:bg-slate-800 rounded-xl text-sm font-semibold">İptal</a><button type="submit" class="px-5 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-semibold hover:bg-blue-700">Güncelle</button></div>
        </form>
    </div>
    """,
      m=m,
      categories=categories,
  )


@app.route("/materials/delete/<int:id>")
@editor_or_admin_required
def delete_material(id):
  m = RawMaterial.query.get_or_404(id)
  db.session.delete(m)
  db.session.commit()
  log_action(session["user_id"], "DELETE_MATERIAL", f"Hammadde silindi: {id}")
  flash("Silindi.", "success")
  return redirect(url_for("materials"))


@app.route("/suppliers")
@login_required
def suppliers():
  if session.get("status") != "active":
    return redirect(url_for("index"))
  search = request.args.get("search", "")
  query = Supplier.query
  if search:
    query = query.filter(
        db.or_(
            Supplier.name.ilike(f"%{search}%"),
            Supplier.city.ilike(f"%{search}%"),
        )
    )
  suppliers_list = query.order_by(Supplier.id.desc()).all()
  return render_page(
      """
    <div class="space-y-6" x-data="{ openAdd: false }">
        <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 bg-white dark:bg-slate-900 p-6 rounded-3xl border border-slate-200 dark:border-slate-800 shadow-sm">
            <div><h1 class="text-2xl font-bold">Firma Yönetimi</h1><p class="text-sm text-slate-500 mt-1">Tedarikçi firma portföyünüzü yönetin.</p></div>
            <button @click="openAdd = true" class="px-5 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-semibold shadow-lg shadow-blue-600/20 hover:bg-blue-700 transition-all inline-flex items-center gap-2"><i class="fa-solid fa-plus"></i> Yeni Firma</button>
        </div>

        <form method="GET" class="bg-white dark:bg-slate-900 p-4 rounded-3xl border border-slate-200 dark:border-slate-800 shadow-sm flex gap-4 items-center">
            <input type="text" name="search" value="{{ search_val }}" placeholder="Firma adı veya şehir..." class="px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm flex-grow outline-none">
            <button type="submit" class="px-6 py-3 bg-slate-900 dark:bg-slate-800 text-white rounded-xl text-sm font-semibold">Ara</button>
            <a href="{{ url_for('suppliers') }}" class="px-6 py-3 bg-slate-100 dark:bg-slate-800 rounded-xl text-sm font-semibold">Sıfırla</a>
        </form>

        <div class="bg-white dark:bg-slate-900 rounded-3xl border border-slate-200 dark:border-slate-800 overflow-hidden shadow-sm">
            <table class="w-full text-left border-collapse">
                <thead>
                    <tr class="bg-slate-100 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 text-xs font-bold text-slate-600 dark:text-slate-300 uppercase">
                        <th class="p-4.5">Firma Adı</th>
                        <th class="p-4.5">Yetkili</th>
                        <th class="p-4.5">Telefon</th>
                        <th class="p-4.5">Şehir</th>
                        <th class="p-4.5">Durum</th>
                        <th class="p-4.5 text-right">İşlemler</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-slate-200 dark:divide-slate-800 text-sm">
                    {% for s in suppliers %}
                    <tr class="hover:bg-slate-50/50 dark:hover:bg-slate-800/40 transition-colors">
                        <td class="p-4.5 font-semibold"><a href="{{ url_for('supplier_detail', id=s.id) }}" class="text-blue-600 dark:text-blue-400 hover:underline">{{ s.name }}</a></td>
                        <td class="p-4.5 text-slate-600 dark:text-slate-300">{{ s.contact_person or '-' }}</td>
                        <td class="p-4.5 text-slate-500">{{ s.phone or '-' }}</td>
                        <td class="p-4.5">{{ s.city or '-' }}</td>
                        <td class="p-4.5"><span class="px-2.5 py-1 rounded-full text-xs font-bold {{ 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300' if s.status=='active' else 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300' }}">{{ 'Aktif' if s.status=='active' else 'Pasif' }}</span></td>
                        <td class="p-4.5 text-right space-x-3">
                            <a href="{{ url_for('supplier_detail', id=s.id) }}" class="text-emerald-600 dark:text-emerald-400 font-semibold hover:underline">Detay</a>
                            {% if session.get('role') in ['admin', 'yonetici'] or s.created_by == session.get('user_id') %}
                            <a href="{{ url_for('edit_supplier', id=s.id) }}" class="text-blue-600 dark:text-blue-400 font-semibold hover:underline">Düzenle</a>
                            {% endif %}
                            {% if session.get('role') in ['admin', 'yonetici'] %}
                            <a href="{{ url_for('delete_supplier', id=s.id) }}" onclick="return confirm('Emin misiniz?')" class="text-rose-600 dark:text-rose-400 font-semibold hover:underline">Sil</a>
                            {% endif %}
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="6" class="p-8 text-center text-slate-500">Kayıt bulunamadı.</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <div x-show="openAdd" class="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50" style="display: none;">
            <div class="bg-white dark:bg-slate-900 p-8 rounded-3xl max-w-lg w-full shadow-2xl border border-slate-200 dark:border-slate-800 space-y-4" @click.outside="openAdd = false">
                <h3 class="text-xl font-bold">Yeni Firma Ekle</h3>
                <form action="{{ url_for('add_supplier') }}" method="POST" class="space-y-4">
                    <div><label class="block text-sm font-semibold mb-1.5">Firma Adı</label><input type="text" name="name" required class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></div>
                    <div class="grid grid-cols-2 gap-4">
                        <div><label class="block text-sm font-semibold mb-1.5">Yetkili</label><input type="text" name="contact_person" class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></div>
                        <div><label class="block text-sm font-semibold mb-1.5">Telefon</label><input type="text" name="phone" class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></div>
                    </div>
                    <div class="grid grid-cols-2 gap-4">
                        <div><label class="block text-sm font-semibold mb-1.5">E-posta</label><input type="email" name="email" class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></div>
                        <div><label class="block text-sm font-semibold mb-1.5">Şehir</label><input type="text" name="city" class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></div>
                    </div>
                    <div><label class="block text-sm font-semibold mb-1.5">Vergi No</label><input type="text" name="tax_no" class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></div>
                    <div><label class="block text-sm font-semibold mb-1.5">Adres</label><textarea name="address" rows="2" class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></textarea></div>
                    <div class="flex justify-end gap-2 pt-2"><button type="button" @click="openAdd = false" class="px-5 py-2.5 bg-slate-200 dark:bg-slate-800 rounded-xl text-sm font-semibold">İptal</button><button type="submit" class="px-5 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-semibold hover:bg-blue-700">Kaydet</button></div>
                </form>
            </div>
        </div>
    </div>
    """,
      suppliers=suppliers_list,
      search_val=search,
  )


@app.route("/suppliers/add", methods=["POST"])
@login_required
def add_supplier():
  if session.get("status") != "active":
    return redirect(url_for("index"))
  s = Supplier(
      name=request.form.get("name").strip(),
      contact_person=request.form.get("contact_person"),
      phone=request.form.get("phone"),
      email=request.form.get("email"),
      address=request.form.get("address"),
      city=request.form.get("city"),
      tax_no=request.form.get("tax_no"),
      notes=request.form.get("notes"),
      created_by=session.get("user_id"),
  )
  db.session.add(s)
  db.session.commit()
  log_action(session["user_id"], "ADD_SUPPLIER", f"Firma eklendi: {s.name}")
  flash("Firma eklendi.", "success")
  return redirect(url_for("suppliers"))


@app.route("/suppliers/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit_supplier(id):
  s = Supplier.query.get_or_404(id)
  if (
      session.get("role") not in ["admin", "yonetici"]
      and s.created_by != session.get("user_id")
  ):
    flash("Yetkiniz yok.", "error")
    return redirect(url_for("suppliers"))

  if request.method == "POST":
    s.name = request.form.get("name").strip()
    s.contact_person = request.form.get("contact_person")
    s.phone = request.form.get("phone")
    s.email = request.form.get("email")
    s.address = request.form.get("address")
    s.city = request.form.get("city")
    s.tax_no = request.form.get("tax_no")
    s.notes = request.form.get("notes")
    s.status = request.form.get("status")
    db.session.commit()
    log_action(session["user_id"], "EDIT_SUPPLIER", f"Firma güncellendi: {id}")
    flash("Güncellendi.", "success")
    return redirect(url_for("suppliers"))

  return render_page(
      """
    <div class="max-w-lg mx-auto bg-white dark:bg-slate-900 p-8 rounded-3xl shadow-xl border border-slate-200 dark:border-slate-800 space-y-4">
        <h2 class="text-2xl font-bold">Firma Düzenle</h2>
        <form method="POST" class="space-y-4">
            <div><label class="block text-sm font-semibold mb-1.5">Firma Adı</label><input type="text" name="name" value="{{ s.name }}" required class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></div>
            <div class="grid grid-cols-2 gap-4">
                <div><label class="block text-sm font-semibold mb-1.5">Yetkili</label><input type="text" name="contact_person" value="{{ s.contact_person or '' }}" class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></div>
                <div><label class="block text-sm font-semibold mb-1.5">Telefon</label><input type="text" name="phone" value="{{ s.phone or '' }}" class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></div>
            </div>
            <div class="grid grid-cols-2 gap-4">
                <div><label class="block text-sm font-semibold mb-1.5">E-posta</label><input type="email" name="email" value="{{ s.email or '' }}" class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></div>
                <div><label class="block text-sm font-semibold mb-1.5">Şehir</label><input type="text" name="city" value="{{ s.city or '' }}" class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></div>
            </div>
            <div><label class="block text-sm font-semibold mb-1.5">Vergi No</label><input type="text" name="tax_no" value="{{ s.tax_no or '' }}" class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></div>
            <div><label class="block text-sm font-semibold mb-1.5">Adres</label><textarea name="address" rows="2" class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none">{{ s.address or '' }}</textarea></div>
            <div><label class="block text-sm font-semibold mb-1.5">Durum</label><select name="status" class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"><option value="active" {{ 'selected' if s.status == 'active' }}>Aktif</option><option value="passive" {{ 'selected' if s.status == 'passive' }}>Pasif</option></select></div>
            <div class="flex justify-end gap-2 pt-2"><a href="{{ url_for('suppliers') }}" class="px-5 py-2.5 bg-slate-200 dark:bg-slate-800 rounded-xl text-sm font-semibold">İptal</a><button type="submit" class="px-5 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-semibold hover:bg-blue-700">Güncelle</button></div>
        </form>
    </div>
    """,
      s=s,
  )


@app.route("/suppliers/detail/<int:id>")
@login_required
def supplier_detail(id):
  s = Supplier.query.get_or_404(id)
  prices_list = (
      Price.query.filter_by(supplier_id=id).order_by(Price.date.desc()).all()
  )
  return render_page(
      """
    <div class="space-y-6">
        <div class="flex justify-between items-center bg-white dark:bg-slate-900 p-6 rounded-3xl border border-slate-200 dark:border-slate-800 shadow-sm">
            <div><h1 class="text-2xl font-bold">{{ s.name }}</h1><p class="text-sm text-slate-500 mt-1">{{ s.city or '-' }} | Yetkili: {{ s.contact_person or '-' }} | Tel: {{ s.phone or '-' }}</p></div>
            <a href="{{ url_for('suppliers') }}" class="px-4 py-2 bg-slate-200 dark:bg-slate-800 rounded-xl text-sm font-semibold hover:bg-slate-300">Firmalara Dön</a>
        </div>
        <div class="bg-white dark:bg-slate-900 p-6 rounded-3xl border border-slate-200 dark:border-slate-800 shadow-sm space-y-4">
            <h3 class="text-lg font-bold">Firma Bilgileri</h3>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
                <div><span class="text-slate-400">E-posta:</span> <span class="font-medium">{{ s.email or '-' }}</span></div>
                <div><span class="text-slate-400">Vergi No:</span> <span class="font-medium">{{ s.tax_no or '-' }}</span></div>
                <div><span class="text-slate-400">Adres:</span> <span class="font-medium">{{ s.address or '-' }}</span></div>
            </div>
        </div>
        <div class="space-y-4">
            <h3 class="text-lg font-bold">Bu Firmaya Ait Fiyat Kayıtları</h3>
            <div class="bg-white dark:bg-slate-900 rounded-3xl border border-slate-200 dark:border-slate-800 overflow-hidden shadow-sm">
                <table class="w-full text-left border-collapse">
                    <thead>
                        <tr class="bg-slate-100 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 text-xs font-bold text-slate-600 dark:text-slate-300 uppercase">
                            <th class="p-4.5">Tarih</th>
                            <th class="p-4.5">Hammadde</th>
                            <th class="p-4.5">Birim Fiyat</th>
                            <th class="p-4.5">Nakliye Durumu</th>
                            <th class="p-4.5">Toplam Maliyet</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-200 dark:divide-slate-800 text-sm">
                        {% for p in prices %}
                        <tr class="hover:bg-slate-50/50 dark:hover:bg-slate-800/40 transition-colors">
                            <td class="p-4.5 text-slate-400 text-xs">{{ p.date }}</td>
                            <td class="p-4.5 font-semibold">{{ p.material.name }}</td>
                            <td class="p-4.5">{{ p.unit_price | tr_num }} {{ p.currency }}</td>
                            <td class="p-4.5">
                                {% if p.shipping_status == 'included' %}<span class="px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">Nakliye Dahil (0 TL)</span>
                                {% elif p.shipping_status == 'excluded' %}<span class="px-2.5 py-1 rounded-full text-xs font-bold bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300">Nakliye Hariç (+{{ p.shipping_cost | tr_num }})</span>
                                {% else %}<span class="px-2.5 py-1 rounded-full text-xs font-bold bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300">Nakliye Belirsiz</span>{% endif %}
                            </td>
                            <td class="p-4.5 font-extrabold text-blue-600">{{ p.shipping_included | tr_num }} {{ p.currency }}</td>
                        </tr>
                        {% else %}
                        <tr><td colspan="5" class="p-8 text-center text-slate-500">Kayıt yok.</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """,
      s=s,
      prices=prices_list,
  )


@app.route("/suppliers/delete/<int:id>")
@editor_or_admin_required
def delete_supplier(id):
  s = Supplier.query.get_or_404(id)
  db.session.delete(s)
  db.session.commit()
  log_action(session["user_id"], "DELETE_SUPPLIER", f"Firma silindi: {id}")
  flash("Firma silindi.", "success")
  return redirect(url_for("suppliers"))


@app.route("/prices")
@login_required
def prices():
  if session.get("status") != "active":
    return redirect(url_for("index"))

  material_id = request.args.get("material_id", "")
  query = Price.query
  if material_id:
    query = query.filter_by(material_id=int(material_id))

  prices_list = query.order_by(Price.date.desc()).all()

  subq = (
      db.session.query(
          Price.material_id,
          db.func.min(Price.shipping_included).label("min_price"),
      )
      .group_by(Price.material_id)
      .subquery()
  )
  comparisons = (
      db.session.query(Price)
      .join(
          subq,
          db.and_(
              Price.material_id == subq.c.material_id,
              Price.shipping_included == subq.c.min_price,
          ),
      )
      .all()
  )

  materials = RawMaterial.query.filter_by(status="active").all()
  suppliers = Supplier.query.filter_by(status="active").all()

  return render_page(
      """
    <div class="space-y-8" x-data="{ openAdd: false }">
        <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 bg-white dark:bg-slate-900 p-6 rounded-3xl border border-slate-200 dark:border-slate-800 shadow-sm">
            <div><h1 class="text-2xl font-bold">Fiyatlar ve Karşılaştırma</h1><p class="text-sm text-slate-500 mt-1">En uygun maliyetli tedarikçileri anlık analiz edin.</p></div>
            <button @click="openAdd = true" class="px-5 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-semibold shadow-lg shadow-blue-600/20 hover:bg-blue-700 transition-all inline-flex items-center gap-2"><i class="fa-solid fa-plus"></i> Yeni Fiyat Ekle</button>
        </div>

        <div class="bg-white dark:bg-slate-900 p-6 rounded-3xl border border-slate-200 dark:border-slate-800 shadow-sm space-y-4">
            <h3 class="text-lg font-bold flex items-center gap-2"><i class="fa-solid fa-ranking-star text-amber-500"></i> En Uygun Tedarikçiler (Özet Analiz)</h3>
            <div class="overflow-x-auto">
                <table class="w-full text-left border-collapse">
                    <thead>
                        <tr class="bg-slate-100 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 text-xs font-bold text-slate-600 dark:text-slate-300 uppercase">
                            <th class="p-3.5">Hammadde</th>
                            <th class="p-3.5">En Ucuz Tedarikçi</th>
                            <th class="p-3.5">Toplam Maliyet (Birim/Nakliye)</th>
                            <th class="p-3.5">Tarih</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-200 dark:divide-slate-800 text-sm">
                        {% for c in comparisons %}
                        <tr class="bg-emerald-50/40 dark:bg-emerald-950/20 hover:bg-emerald-50/80 transition-colors">
                            <td class="p-3.5 font-semibold">{{ c.material.name }} <span class="text-xs text-slate-400">({{ c.material.code }})</span></td>
                            <td class="p-3.5 font-extrabold text-emerald-700 dark:text-emerald-400 flex items-center gap-1.5"><i class="fa-solid fa-circle-check text-xs"></i> {{ c.supplier.name }}</td>
                            <td class="p-3.5 font-extrabold">{{ c.shipping_included | tr_num }} {{ c.currency }} / {{ c.material.unit }}</td>
                            <td class="p-3.5 text-slate-400 text-xs">{{ c.date }}</td>
                        </tr>
                        {% else %}
                        <tr><td colspan="4" class="p-6 text-center text-slate-500">Analiz verisi bulunamadı.</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>

        <div class="space-y-4">
            <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                <h3 class="text-lg font-bold">Tüm Fiyat Kayıtları</h3>
                <form method="GET" class="flex gap-2">
                    <select name="material_id" onchange="this.form.submit()" class="px-4 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none">
                        <option value="">Tüm Hammaddeler</option>
                        {% for m in materials %}<option value="{{ m.id }}" {{ 'selected' if mat_val == m.id|string }}>{{ m.name }}</option>{% endfor %}
                    </select>
                </form>
            </div>
            <div class="bg-white dark:bg-slate-900 rounded-3xl border border-slate-200 dark:border-slate-800 overflow-hidden shadow-sm">
                <table class="w-full text-left border-collapse">
                    <thead>
                        <tr class="bg-slate-100 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 text-xs font-bold text-slate-600 dark:text-slate-300 uppercase">
                            <th class="p-4.5">Tarih</th>
                            <th class="p-4.5">Hammadde</th>
                            <th class="p-4.5">Firma</th>
                            <th class="p-4.5">Birim Fiyat</th>
                            <th class="p-4.5">Nakliye Durumu</th>
                            <th class="p-4.5">Toplam Fiyat</th>
                            <th class="p-4.5 text-right">İşlem</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-200 dark:divide-slate-800 text-sm">
                        {% for p in prices %}
                        <tr class="hover:bg-slate-50/50 dark:hover:bg-slate-800/40 transition-colors">
                            <td class="p-4.5 text-slate-400 text-xs">{{ p.date }}</td>
                            <td class="p-4.5 font-semibold">{{ p.material.name }}</td>
                            <td class="p-4.5 text-slate-600 dark:text-slate-300">{{ p.supplier.name }}</td>
                            <td class="p-4.5">{{ p.unit_price | tr_num }} {{ p.currency }}</td>
                            <td class="p-4.5">
                                {% if p.shipping_status == 'included' %}<span class="px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">Nakliye Dahil (0 TL)</span>
                                {% elif p.shipping_status == 'excluded' %}<span class="px-2.5 py-1 rounded-full text-xs font-bold bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300">Nakliye Hariç (+{{ p.shipping_cost | tr_num }})</span>
                                {% else %}<span class="px-2.5 py-1 rounded-full text-xs font-bold bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300">Nakliye Belirsiz</span>{% endif %}
                            </td>
                            <td class="p-4.5 font-extrabold text-blue-600">{{ p.shipping_included | tr_num }} {{ p.currency }}</td>
                            <td class="p-4.5 text-right">{% if session.get('role') in ['admin', 'yonetici'] %}<a href="{{ url_for('delete_price', id=p.id) }}" onclick="return confirm('Emin misiniz?')" class="text-rose-600 dark:text-rose-400 text-xs font-semibold hover:underline">Sil</a>{% endif %}</td>
                        </tr>
                        {% else %}
                        <tr><td colspan="7" class="p-8 text-center text-slate-500">Kayıt bulunamadı.</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>

        <div x-show="openAdd" class="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50" style="display: none;" x-data="{ shippingStatus: 'included' }">
            <div class="bg-white dark:bg-slate-900 p-8 rounded-3xl max-w-lg w-full shadow-2xl border border-slate-200 dark:border-slate-800 space-y-4" @click.outside="openAdd = false">
                <h3 class="text-xl font-bold">Yeni Fiyat Ekle</h3>
                <form action="{{ url_for('add_price') }}" method="POST" class="space-y-4">
                    <div class="grid grid-cols-2 gap-4">
                        <div><label class="block text-sm font-semibold mb-1.5">Hammadde</label><select name="material_id" required class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none">{% for m in materials %}<option value="{{ m.id }}">{{ m.name }} ({{ m.unit }})</option>{% endfor %}</select></div>
                        <div><label class="block text-sm font-semibold mb-1.5">Firma</label><select name="supplier_id" required class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none">{% for s in suppliers %}<option value="{{ s.id }}">{{ s.name }}</option>{% endfor %}</select></div>
                    </div>
                    <div class="grid grid-cols-3 gap-4">
                        <div><label class="block text-sm font-semibold mb-1.5">Tarih</label><input type="date" name="date" value="{{ today }}" required class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></div>
                        <div><label class="block text-sm font-semibold mb-1.5">Birim</label><select name="currency" class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"><option value="TL">TL</option><option value="USD">USD</option><option value="EUR">EUR</option></select></div>
                        <div><label class="block text-sm font-semibold mb-1.5">Birim Fiyat</label><input type="number" step="0.01" name="unit_price" required class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none"></div>
                    </div>
                    <div class="grid grid-cols-2 gap-4">
                        <div>
                            <label class="block text-sm font-semibold mb-1.5">Nakliye Durumu</label>
                            <select name="shipping_status" x-model="shippingStatus" class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none">
                                <option value="included">Nakliye Dahil (0 TL)</option>
                                <option value="excluded">Nakliye Hariç / Ek Ücret (kg/ton)</option>
                                <option value="unknown">Nakliye Fiyatı Belirsiz</option>
                            </select>
                        </div>
                        <div x-show="shippingStatus === 'excluded'">
                            <label class="block text-sm font-semibold mb-1.5">Nakliye (kg/ton)</label>
                            <input type="number" step="0.01" name="shipping_cost" value="0" class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 dark:bg-slate-800 text-sm outline-none">
                        </div>
                    </div>
                    <div class="flex justify-end gap-2 pt-2"><button type="button" @click="openAdd = false" class="px-5 py-2.5 bg-slate-200 dark:bg-slate-800 rounded-xl text-sm font-semibold">İptal</button><button type="submit" class="px-5 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-semibold hover:bg-blue-700">Kaydet</button></div>
                </form>
            </div>
        </div>
    </div>
    """,
      prices=prices_list,
      comparisons=comparisons,
      materials=materials,
      suppliers=suppliers,
      today=datetime.now().strftime("%Y-%m-%d"),
      mat_val=material_id,
  )


@app.route("/prices/add", methods=["POST"])
@login_required
def add_price():
  if session.get("status") != "active":
    return redirect(url_for("index"))

  unit_price = float(request.form.get("unit_price") or 0)
  shipping_status = request.form.get("shipping_status", "included")

  if shipping_status in ["included", "unknown"]:
    shipping_cost = 0.0
  else:
    shipping_cost = float(request.form.get("shipping_cost") or 0)

  shipping_excluded = unit_price
  shipping_included = unit_price + shipping_cost

  p = Price(
      material_id=request.form.get("material_id"),
      supplier_id=request.form.get("supplier_id"),
      date=request.form.get("date"),
      currency=request.form.get("currency"),
      unit_price=unit_price,
      shipping_status=shipping_status,
      shipping_cost=shipping_cost,
      shipping_excluded=shipping_excluded,
      shipping_included=shipping_included,
      created_by=session.get("user_id"),
  )
  db.session.add(p)
  db.session.commit()
  log_action(session["user_id"], "ADD_PRICE", "Fiyat kaydı eklendi")
  flash("Fiyat eklendi.", "success")
  return redirect(url_for("prices"))


@app.route("/prices/delete/<int:id>")
@editor_or_admin_required
def delete_price(id):
  p = Price.query.get_or_404(id)
  db.session.delete(p)
  db.session.commit()
  log_action(session["user_id"], "DELETE_PRICE", f"Fiyat silindi: {id}")
  flash("Silindi.", "success")
  return redirect(url_for("prices"))


if __name__ == "__main__":
  app.run(debug=True, port=5000)
