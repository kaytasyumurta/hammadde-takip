# app.py - Hammadde Fiyat ve Takip Sistemi (Bulut & SQLAlchemy Uyumlu)
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
  shipping_type = db.Column(db.String(20), nullable=False, default="per_unit")
  shipping_cost = db.Column(db.Float, default=0)
  shipping_excluded = db.Column(db.Float, nullable=False)
  shipping_included = db.Column(db.Float, nullable=False)
  valid_until = db.Column(db.String(20))
  notes = db.Column(db.Text)
  created_by = db.Column(db.Integer, db.ForeignKey("users.id"))

  material = db.relationship("RawMaterial", backref="prices")
  supplier = db.relationship("Supplier", backref="prices")


with app.app_context():
  db.create_all()
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


def render_page(content_html, **kwargs):
  base = """
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
    </head>
    <body class="bg-slate-50 dark:bg-slate-900 text-slate-800 dark:text-slate-100 min-h-screen flex flex-col transition-colors duration-200">
        <nav class="bg-white dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 shadow-sm sticky top-0 z-50">
            <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                <div class="flex justify-between h-16">
                    <div class="flex items-center space-x-8">
                        <a href="{{ url_for('index') }}" class="font-bold text-xl text-blue-600 dark:text-blue-400 flex items-center gap-2">
                            <i class="fa-solid fa-boxes-stacked"></i> Hammadde Takip
                        </a>
                        {% if session.get('user_id') and session.get('status') == 'active' %}
                        <div class="hidden md:flex space-x-4">
                            <a href="{{ url_for('materials') }}" class="px-3 py-2 rounded-md text-sm font-medium hover:bg-slate-100 dark:hover:bg-slate-700">Hammaddeler</a>
                            <a href="{{ url_for('suppliers') }}" class="px-3 py-2 rounded-md text-sm font-medium hover:bg-slate-100 dark:hover:bg-slate-700">Firmalar</a>
                            <a href="{{ url_for('prices') }}" class="px-3 py-2 rounded-md text-sm font-medium hover:bg-slate-100 dark:hover:bg-slate-700">Fiyatlar ve Karşılaştırma</a>
                            {% if session.get('role') in ['admin', 'yonetici'] %}
                            <a href="{{ url_for('logs') }}" class="px-3 py-2 rounded-md text-sm font-medium hover:bg-slate-100 dark:hover:bg-slate-700">Loglar</a>
                            {% endif %}
                            {% if session.get('role') == 'admin' %}
                            <a href="{{ url_for('admin_users') }}" class="px-3 py-2 rounded-md text-sm font-medium text-amber-600 dark:text-amber-400 hover:bg-slate-100 dark:hover:bg-slate-700">Kullanıcı Yönetimi</a>
                            {% endif %}
                        </div>
                        {% endif %}
                    </div>
                    <div class="flex items-center space-x-4">
                        <button @click="darkMode = !darkMode; localStorage.setItem('darkMode', darkMode)" class="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700">
                            <i class="fa-solid" :class="darkMode ? 'fa-sun text-yellow-400' : 'fa-moon text-slate-600'"></i>
                        </button>
                        {% if session.get('user_id') %}
                            <div class="text-sm font-medium hidden sm:block">
                                {{ session.get('username') }} <span class="text-xs px-2 py-0.5 rounded bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200 uppercase">{{ session.get('role') }}</span>
                            </div>
                            <a href="{{ url_for('logout') }}" class="px-3 py-2 text-sm font-medium bg-rose-50 dark:bg-rose-900/30 text-rose-600 dark:text-rose-400 rounded-md hover:bg-rose-100">Çıkış</a>
                        {% else %}
                            <a href="{{ url_for('login') }}" class="text-sm font-medium hover:text-blue-600">Giriş Yap</a>
                            <a href="{{ url_for('register') }}" class="px-4 py-2 text-sm font-medium bg-blue-600 text-white rounded-md hover:bg-blue-700 shadow-sm">Kayıt Ol</a>
                        {% endif %}
                    </div>
                </div>
            </div>
        </nav>
        <div class="max-w-7xl mx-auto px-4 mt-4 w-full">
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message %}
                        <div class="p-4 mb-4 rounded-lg text-sm border {{ 'bg-emerald-50 border-emerald-200 text-emerald-800 dark:bg-emerald-900/30 dark:border-emerald-800 dark:text-emerald-300' if category == 'success' else 'bg-rose-50 border-rose-200 text-rose-800 dark:bg-rose-900/30 dark:border-rose-800 dark:text-rose-300' }}">
                            {{ message }}
                        </div>
                    {% endfor %}
                {% endif %}
            {% endwith %}
        </div>
        <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 flex-grow w-full">
            {{ content_html | safe }}
        </main>
        <footer class="bg-white dark:bg-slate-800 border-t border-slate-200 dark:border-slate-700 py-4 text-center text-xs text-slate-500">
            Hammadde Fiyat ve Takip Sistemi &copy; 2026 | Bulut Veritabanı Entegrasyonlu
        </footer>
    </body>
    </html>
    """
  return render_template_string(base, **kwargs)


@app.route("/")
def index():
  if "user_id" not in session:
    return render_page("""
        <div class="max-w-xl mx-auto text-center py-16">
            <h1 class="text-4xl font-extrabold tracking-tight mb-4">Hammadde ve Tedarik Takip Sistemi</h1>
            <p class="text-slate-600 dark:text-slate-400 mb-8">Bulut tabanlı güvenli altyapı ile hammadde fiyatlarını ve tedarikçileri her yerden yönetin.</p>
            <div class="flex justify-center gap-4">
                <a href="%s" class="px-6 py-3 bg-blue-600 text-white font-medium rounded-lg shadow hover:bg-blue-700">Giriş Yap</a>
                <a href="%s" class="px-6 py-3 bg-slate-200 dark:bg-slate-700 font-medium rounded-lg hover:bg-slate-300">Kayıt Ol</a>
            </div>
        </div>
        """ % (url_for('login'), url_for('register')))

  if session.get("status") == "pending":
    return render_page(f"""
        <div class="max-w-md mx-auto text-center py-16 bg-white dark:bg-slate-800 p-8 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700">
            <i class="fa-solid fa-clock-rotate-left text-amber-500 text-5xl mb-4"></i>
            <h2 class="text-2xl font-bold mb-2">Hesabınız Onay Bekliyor</h2>
            <p class="text-slate-600 dark:text-slate-400 mb-6">Yönetici onayından sonra tüm özelliklere erişebileceksiniz.</p>
            <a href="{url_for('logout')}" class="px-4 py-2 bg-slate-200 dark:bg-slate-700 rounded-lg text-sm font-medium">Çıkış Yap</a>
        </div>
        """)

  m_count = RawMaterial.query.count()
  s_count = Supplier.query.count()
  p_count = Price.query.count()

  return render_page(
      """
    <div class="space-y-6">
        <div class="flex justify-between items-center">
            <h1 class="text-2xl font-bold">Kontrol Paneli</h1>
            <span class="text-sm text-slate-500">Hoş geldiniz, {{ session.get('username') }}</span>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div class="bg-white dark:bg-slate-800 p-6 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm flex items-center justify-between">
                <div><p class="text-sm font-medium text-slate-500">Toplam Hammadde</p><p class="text-3xl font-bold mt-1">{{ m_count }}</p></div>
                <div class="p-3 bg-blue-50 dark:bg-blue-900/30 text-blue-600 rounded-lg text-xl"><i class="fa-solid fa-cube"></i></div>
            </div>
            <div class="bg-white dark:bg-slate-800 p-6 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm flex items-center justify-between">
                <div><p class="text-sm font-medium text-slate-500">Kayıtlı Tedarikçiler</p><p class="text-3xl font-bold mt-1">{{ s_count }}</p></div>
                <div class="p-3 bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 rounded-lg text-xl"><i class="fa-solid fa-truck"></i></div>
            </div>
            <div class="bg-white dark:bg-slate-800 p-6 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm flex items-center justify-between">
                <div><p class="text-sm font-medium text-slate-500">Fiyat Kayıtları</p><p class="text-3xl font-bold mt-1">{{ p_count }}</p></div>
                <div class="p-3 bg-amber-50 dark:bg-amber-900/30 text-amber-600 rounded-lg text-xl"><i class="fa-solid fa-tag"></i></div>
            </div>
        </div>
        <div class="bg-white dark:bg-slate-800 p-6 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm">
            <h3 class="text-lg font-bold mb-4">Hızlı Erişim</h3>
            <div class="flex flex-wrap gap-4">
                <a href="{{ url_for('materials') }}" class="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700">Hammaddeleri Yönet</a>
                <a href="{{ url_for('suppliers') }}" class="px-4 py-2 bg-emerald-600 text-white rounded-lg text-sm font-medium hover:bg-emerald-700">Firmaları Yönet</a>
                <a href="{{ url_for('prices') }}" class="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700">Fiyat Karşılaştırma</a>
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
    except Exception:
      db.session.rollback()
      flash("Bu kullanıcı adı veya e-posta zaten kullanımda.", "error")

  return render_page("""
    <div class="max-w-md mx-auto bg-white dark:bg-slate-800 p-8 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700">
        <h2 class="text-2xl font-bold mb-6 text-center">Kayıt Ol</h2>
        <form method="POST" class="space-y-4">
            <div><label class="block text-sm font-medium mb-1">Kullanıcı Adı</label><input type="text" name="username" required class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></div>
            <div><label class="block text-sm font-medium mb-1">E-posta</label><input type="email" name="email" required class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></div>
            <div><label class="block text-sm font-medium mb-1">Şifre</label><input type="password" name="password" required class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></div>
            <button type="submit" class="w-full py-2 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700">Kayıt Ol</button>
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
    <div class="max-w-md mx-auto bg-white dark:bg-slate-800 p-8 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700">
        <h2 class="text-2xl font-bold mb-6 text-center">Giriş Yap</h2>
        <form method="POST" class="space-y-4">
            <div><label class="block text-sm font-medium mb-1">Kullanıcı Adı</label><input type="text" name="username" required class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></div>
            <div><label class="block text-sm font-medium mb-1">Şifre</label><input type="password" name="password" required class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></div>
            <button type="submit" class="w-full py-2 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700">Giriş Yap</button>
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


@app.route("/admin/users")
@admin_required
def admin_users():
  users = User.query.order_by(User.id.desc()).all()
  return render_page(
      """
    <div class="space-y-6">
        <h1 class="text-2xl font-bold">Kullanıcı Yönetimi</h1>
        <div class="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden shadow-sm">
            <table class="w-full text-left border-collapse">
                <thead><tr class="bg-slate-50 dark:bg-slate-700/50 border-b border-slate-200 dark:border-slate-700 text-xs font-semibold text-slate-500 uppercase"><th class="p-4">Kullanıcı Adı</th><th class="p-4">E-posta</th><th class="p-4">Rol</th><th class="p-4">Durum</th><th class="p-4 text-right">İşlemler</th></tr></thead>
                <tbody class="divide-y divide-slate-200 dark:divide-slate-700 text-sm">
                    {% for u in users %}
                    <tr>
                        <td class="p-4 font-medium">{{ u.username }}</td>
                        <td class="p-4 text-slate-500">{{ u.email }}</td>
                        <td class="p-4">
                            <form action="{{ url_for('admin_update_user', user_id=u.id) }}" method="POST" class="flex items-center gap-2">
                                <select name="role" class="px-2 py-1 border rounded text-xs dark:bg-slate-700 dark:border-slate-600">
                                    <option value="admin" {{ 'selected' if u.role=='admin' }}>Admin</option>
                                    <option value="yonetici" {{ 'selected' if u.role=='yonetici' }}>Yönetici</option>
                                    <option value="personel" {{ 'selected' if u.role=='personel' }}>Personel</option>
                                    <option value="goruntuleyen" {{ 'selected' if u.role=='goruntuleyen' }}>Görüntüleyen</option>
                                </select>
                        </td>
                        <td class="p-4">
                                <select name="status" class="px-2 py-1 border rounded text-xs dark:bg-slate-700 dark:border-slate-600">
                                    <option value="active" {{ 'selected' if u.status=='active' }}>Aktif</option>
                                    <option value="pending" {{ 'selected' if u.status=='pending' }}>Onay Bekliyor</option>
                                    <option value="passive" {{ 'selected' if u.status=='passive' }}>Pasif</option>
                                </select>
                        </td>
                        <td class="p-4 text-right"><button type="submit" class="px-3 py-1 bg-blue-600 text-white rounded text-xs font-medium hover:bg-blue-700">Güncelle</button></form></td>
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
        <h1 class="text-2xl font-bold">İşlem Geçmişi (Loglar)</h1>
        <div class="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden shadow-sm">
            <table class="w-full text-left border-collapse">
                <thead><tr class="bg-slate-50 dark:bg-slate-700/50 border-b border-slate-200 dark:border-slate-700 text-xs font-semibold text-slate-500 uppercase"><th class="p-4">Tarih</th><th class="p-4">Kullanıcı</th><th class="p-4">İşlem</th><th class="p-4">Detay</th></tr></thead>
                <tbody class="divide-y divide-slate-200 dark:divide-slate-700 text-sm">
                    {% for l, u in logs %}
                    <tr>
                        <td class="p-4 text-slate-500 text-xs">{{ l.timestamp.strftime('%Y-%m-%d %H:%M:%S') }}</td>
                        <td class="p-4 font-medium">{{ u.username if u else 'Sistem' }}</td>
                        <td class="p-4"><span class="px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-700 text-xs font-mono">{{ l.action }}</span></td>
                        <td class="p-4 text-slate-600 dark:text-slate-300">{{ l.details }}</td>
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
  categories = Category.query.all()

  return render_page(
      """
    <div class="space-y-6" x-data="{ openAdd: false }">
        <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
            <h1 class="text-2xl font-bold">Hammadde Yönetimi</h1>
            <button @click="openAdd = true" class="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700"><i class="fa-solid fa-plus mr-1"></i> Yeni Ekle</button>
        </div>
        <form method="GET" class="bg-white dark:bg-slate-800 p-4 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm flex flex-wrap gap-4 items-center">
            <input type="text" name="search" value="{{ request.args.get('search', '') }}" placeholder="Hammadde adı/kodu..." class="px-3 py-2 border rounded-lg text-sm dark:bg-slate-700 dark:border-slate-600 flex-grow">
            <select name="category" class="px-3 py-2 border rounded-lg text-sm dark:bg-slate-700 dark:border-slate-600">
                <option value="">Tüm Kategoriler</option>
                {% for c in categories %}
                <option value="{{ c.id }}" {{ 'selected' if request.args.get('category') == c.id|string }}>{{ c.name }}</option>
                {% endfor %}
            </select>
            <button type="submit" class="px-4 py-2 bg-slate-800 text-white dark:bg-slate-700 rounded-lg text-sm">Filtrele</button>
            <a href="{{ url_for('materials') }}" class="px-4 py-2 bg-slate-100 dark:bg-slate-700 rounded-lg text-sm">Sıfırla</a>
        </form>
        <div class="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden shadow-sm">
            <table class="w-full text-left border-collapse">
                <thead><tr class="bg-slate-50 dark:bg-slate-700/50 border-b border-slate-200 dark:border-slate-700 text-xs font-semibold text-slate-500 uppercase"><th class="p-4">Kod</th><th class="p-4">Adı</th><th class="p-4">Kategori</th><th class="p-4">Birim</th><th class="p-4">Durum</th><th class="p-4 text-right">İşlemler</th></tr></thead>
                <tbody class="divide-y divide-slate-200 dark:divide-slate-700 text-sm">
                    {% for m in materials %}
                    <tr>
                        <td class="p-4 font-mono font-medium">{{ m.code }}</td>
                        <td class="p-4 font-medium">{{ m.name }}</td>
                        <td class="p-4 text-slate-500">{{ m.category.name if m.category else '-' }}</td>
                        <td class="p-4">{{ m.unit }}</td>
                        <td class="p-4"><span class="px-2 py-0.5 rounded text-xs {{ 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300' if m.status=='active' else 'bg-slate-100 text-slate-800 dark:bg-slate-700 dark:text-slate-300' }}">{{ 'Aktif' if m.status=='active' else 'Pasif' }}</span></td>
                        <td class="p-4 text-right space-x-2">
                            {% if session.get('role') in ['admin', 'yonetici'] or m.created_by == session.get('user_id') %}
                            <a href="{{ url_for('edit_material', id=m.id) }}" class="text-blue-600 hover:underline">Düzenle</a>
                            {% endif %}
                            {% if session.get('role') in ['admin', 'yonetici'] %}
                            <a href="{{ url_for('delete_material', id=m.id) }}" onclick="return confirm('Emin misiniz?')" class="text-rose-600 hover:underline">Sil</a>
                            {% endif %}
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="6" class="p-6 text-center text-slate-500">Kayıt bulunamadı.</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        <div x-show="openAdd" class="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50" style="display: none;">
            <div class="bg-white dark:bg-slate-800 p-6 rounded-xl max-w-lg w-full shadow-lg" @click.outside="openAdd = false">
                <h3 class="text-lg font-bold mb-4">Yeni Hammadde Ekle</h3>
                <form action="{{ url_for('add_material') }}" method="POST" class="space-y-4">
                    <div><label class="block text-sm font-medium mb-1">Kod</label><input type="text" name="code" required class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></div>
                    <div><label class="block text-sm font-medium mb-1">Adı</label><input type="text" name="name" required class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></div>
                    <div><label class="block text-sm font-medium mb-1">Kategori</label><select name="category_id" class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600">{% for c in categories %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></div>
                    <div><label class="block text-sm font-medium mb-1">Birim</label><select name="unit" class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"><option value="kg">kg</option><option value="ton">ton</option><option value="litre">litre</option><option value="adet">adet</option></select></div>
                    <div><label class="block text-sm font-medium mb-1">Açıklama</label><textarea name="description" rows="2" class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></textarea></div>
                    <div class="flex justify-end gap-2"><button type="button" @click="openAdd = false" class="px-4 py-2 bg-slate-200 dark:bg-slate-700 rounded-lg text-sm">İptal</button><button type="submit" class="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm">Kaydet</button></div>
                </form>
            </div>
        </div>
    </div>
    """,
      materials=materials_list,
      categories=categories,
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
  except Exception:
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

  categories = Category.query.all()
  return render_page(
      """
    <div class="max-w-lg mx-auto bg-white dark:bg-slate-800 p-8 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700">
        <h2 class="text-2xl font-bold mb-6">Hammadde Düzenle</h2>
        <form method="POST" class="space-y-4">
            <div><label class="block text-sm font-medium mb-1">Kod</label><input type="text" name="code" value="{{ m.code }}" required class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></div>
            <div><label class="block text-sm font-medium mb-1">Adı</label><input type="text" name="name" value="{{ m.name }}" required class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></div>
            <div><label class="block text-sm font-medium mb-1">Kategori</label><select name="category_id" class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600">{% for c in categories %}<option value="{{ c.id }}" {{ 'selected' if m.category_id == c.id }}>{{ c.name }}</option>{% endfor %}</select></div>
            <div><label class="block text-sm font-medium mb-1">Birim</label><select name="unit" class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600">{% for u in ['kg', 'ton', 'litre', 'adet'] %}<option value="{{ u }}" {{ 'selected' if m.unit == u }}>{{ u }}</option>{% endfor %}</select></div>
            <div><label class="block text-sm font-medium mb-1">Açıklama</label><textarea name="description" rows="2" class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600">{{ m.description }}</textarea></div>
            <div><label class="block text-sm font-medium mb-1">Durum</label><select name="status" class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"><option value="active" {{ 'selected' if m.status == 'active' }}>Aktif</option><option value="passive" {{ 'selected' if m.status == 'passive' }}>Pasif</option></select></div>
            <div class="flex justify-end gap-2"><a href="{{ url_for('materials') }}" class="px-4 py-2 bg-slate-200 dark:bg-slate-700 rounded-lg text-sm">İptal</a><button type="submit" class="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm">Güncelle</button></div>
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
        <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
            <h1 class="text-2xl font-bold">Firma Yönetimi</h1>
            <button @click="openAdd = true" class="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700"><i class="fa-solid fa-plus mr-1"></i> Yeni Firma Ekle</button>
        </div>
        <form method="GET" class="bg-white dark:bg-slate-800 p-4 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm flex gap-4 items-center">
            <input type="text" name="search" value="{{ request.args.get('search', '') }}" placeholder="Firma adı veya şehir..." class="px-3 py-2 border rounded-lg text-sm dark:bg-slate-700 dark:border-slate-600 flex-grow">
            <button type="submit" class="px-4 py-2 bg-slate-800 text-white dark:bg-slate-700 rounded-lg text-sm">Ara</button>
            <a href="{{ url_for('suppliers') }}" class="px-4 py-2 bg-slate-100 dark:bg-slate-700 rounded-lg text-sm">Sıfırla</a>
        </form>
        <div class="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden shadow-sm">
            <table class="w-full text-left border-collapse">
                <thead><tr class="bg-slate-50 dark:bg-slate-700/50 border-b border-slate-200 dark:border-slate-700 text-xs font-semibold text-slate-500 uppercase"><th class="p-4">Firma Adı</th><th class="p-4">Yetkili</th><th class="p-4">Telefon</th><th class="p-4">Şehir</th><th class="p-4">Durum</th><th class="p-4 text-right">İşlemler</th></tr></thead>
                <tbody class="divide-y divide-slate-200 dark:divide-slate-700 text-sm">
                    {% for s in suppliers %}
                    <tr>
                        <td class="p-4 font-medium"><a href="{{ url_for('supplier_detail', id=s.id) }}" class="text-blue-600 hover:underline">{{ s.name }}</a></td>
                        <td class="p-4 text-slate-600 dark:text-slate-300">{{ s.contact_person }}</td>
                        <td class="p-4 text-slate-500">{{ s.phone }}</td>
                        <td class="p-4">{{ s.city }}</td>
                        <td class="p-4"><span class="px-2 py-0.5 rounded text-xs {{ 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300' if s.status=='active' else 'bg-slate-100 text-slate-800 dark:bg-slate-700 dark:text-slate-300' }}">{{ 'Aktif' if s.status=='active' else 'Pasif' }}</span></td>
                        <td class="p-4 text-right space-x-2">
                            <a href="{{ url_for('supplier_detail', id=s.id) }}" class="text-emerald-600 hover:underline">Detay</a>
                            {% if session.get('role') in ['admin', 'yonetici'] or s.created_by == session.get('user_id') %}
                            <a href="{{ url_for('edit_supplier', id=s.id) }}" class="text-blue-600 hover:underline">Düzenle</a>
                            {% endif %}
                            {% if session.get('role') in ['admin', 'yonetici'] %}
                            <a href="{{ url_for('delete_supplier', id=s.id) }}" onclick="return confirm('Emin misiniz?')" class="text-rose-600 hover:underline">Sil</a>
                            {% endif %}
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="6" class="p-6 text-center text-slate-500">Kayıt bulunamadı.</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        <div x-show="openAdd" class="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50" style="display: none;">
            <div class="bg-white dark:bg-slate-800 p-6 rounded-xl max-w-lg w-full shadow-lg" @click.outside="openAdd = false">
                <h3 class="text-lg font-bold mb-4">Yeni Firma Ekle</h3>
                <form action="{{ url_for('add_supplier') }}" method="POST" class="space-y-4">
                    <div><label class="block text-sm font-medium mb-1">Firma Adı</label><input type="text" name="name" required class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></div>
                    <div class="grid grid-cols-2 gap-4">
                        <div><label class="block text-sm font-medium mb-1">Yetkili</label><input type="text" name="contact_person" class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></div>
                        <div><label class="block text-sm font-medium mb-1">Telefon</label><input type="text" name="phone" class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></div>
                    </div>
                    <div class="grid grid-cols-2 gap-4">
                        <div><label class="block text-sm font-medium mb-1">E-posta</label><input type="email" name="email" class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></div>
                        <div><label class="block text-sm font-medium mb-1">Şehir</label><input type="text" name="city" class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></div>
                    </div>
                    <div><label class="block text-sm font-medium mb-1">Vergi No</label><input type="text" name="tax_no" class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></div>
                    <div><label class="block text-sm font-medium mb-1">Adres</label><textarea name="address" rows="2" class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></textarea></div>
                    <div class="flex justify-end gap-2"><button type="button" @click="openAdd = false" class="px-4 py-2 bg-slate-200 dark:bg-slate-700 rounded-lg text-sm">İptal</button><button type="submit" class="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm">Kaydet</button></div>
                </form>
            </div>
        </div>
    </div>
    """,
      suppliers=suppliers_list,
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
    <div class="max-w-lg mx-auto bg-white dark:bg-slate-800 p-8 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700">
        <h2 class="text-2xl font-bold mb-6">Firma Düzenle</h2>
        <form method="POST" class="space-y-4">
            <div><label class="block text-sm font-medium mb-1">Firma Adı</label><input type="text" name="name" value="{{ s.name }}" required class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></div>
            <div class="grid grid-cols-2 gap-4">
                <div><label class="block text-sm font-medium mb-1">Yetkili</label><input type="text" name="contact_person" value="{{ s.contact_person }}" class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></div>
                <div><label class="block text-sm font-medium mb-1">Telefon</label><input type="text" name="phone" value="{{ s.phone }}" class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></div>
            </div>
            <div class="grid grid-cols-2 gap-4">
                <div><label class="block text-sm font-medium mb-1">E-posta</label><input type="email" name="email" value="{{ s.email }}" class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></div>
                <div><label class="block text-sm font-medium mb-1">Şehir</label><input type="text" name="city" value="{{ s.city }}" class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></div>
            </div>
            <div><label class="block text-sm font-medium mb-1">Vergi No</label><input type="text" name="tax_no" value="{{ s.tax_no }}" class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></div>
            <div><label class="block text-sm font-medium mb-1">Adres</label><textarea name="address" rows="2" class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600">{{ s.address }}</textarea></div>
            <div><label class="block text-sm font-medium mb-1">Durum</label><select name="status" class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"><option value="active" {{ 'selected' if s.status == 'active' }}>Aktif</option><option value="passive" {{ 'selected' if s.status == 'passive' }}>Pasif</option></select></div>
            <div class="flex justify-end gap-2"><a href="{{ url_for('suppliers') }}" class="px-4 py-2 bg-slate-200 dark:bg-slate-700 rounded-lg text-sm">İptal</a><button type="submit" class="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm">Güncelle</button></div>
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
        <div class="flex justify-between items-center">
            <div><h1 class="text-2xl font-bold">{{ s.name }}</h1><p class="text-sm text-slate-500">{{ s.city }} | Yetkili: {{ s.contact_person }} | Tel: {{ s.phone }}</p></div>
            <a href="{{ url_for('suppliers') }}" class="px-4 py-2 bg-slate-200 dark:bg-slate-700 rounded-lg text-sm">Firmalara Dön</a>
        </div>
        <div class="bg-white dark:bg-slate-800 p-6 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm space-y-4">
            <h3 class="text-lg font-bold">Firma Bilgileri</h3>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
                <div><span class="text-slate-500">E-posta:</span> {{ s.email or '-' }}</div>
                <div><span class="text-slate-500">Vergi No:</span> {{ s.tax_no or '-' }}</div>
                <div><span class="text-slate-500">Adres:</span> {{ s.address or '-' }}</div>
            </div>
        </div>
        <div class="space-y-4">
            <h3 class="text-lg font-bold">Bu Firmaya Ait Fiyat Kayıtları</h3>
            <div class="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden shadow-sm">
                <table class="w-full text-left border-collapse">
                    <thead><tr class="bg-slate-50 dark:bg-slate-700/50 border-b border-slate-200 dark:border-slate-700 text-xs font-semibold text-slate-500 uppercase"><th class="p-4">Tarih</th><th class="p-4">Hammadde</th><th class="p-4">Birim Fiyat</th><th class="p-4">Nakliye Hariç</th><th class="p-4">Nakliye Dahil</th></tr></thead>
                    <tbody class="divide-y divide-slate-200 dark:divide-slate-700 text-sm">
                        {% for p in prices %}
                        <tr>
                            <td class="p-4 text-slate-500">{{ p.date }}</td>
                            <td class="p-4 font-medium">{{ p.material.name }}</td>
                            <td class="p-4">{{ p.unit_price | tr_num }} {{ p.currency }}</td>
                            <td class="p-4 font-medium">{{ p.shipping_excluded | tr_num }} {{ p.currency }}</td>
                            <td class="p-4 font-bold text-blue-600">{{ p.shipping_included | tr_num }} {{ p.currency }}</td>
                        </tr>
                        {% else %}
                        <tr><td colspan="5" class="p-6 text-center text-slate-500">Kayıt yok.</td></tr>
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
        <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
            <h1 class="text-2xl font-bold">Fiyatlar ve Karşılaştırma</h1>
            <button @click="openAdd = true" class="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700"><i class="fa-solid fa-plus mr-1"></i> Yeni Fiyat Ekle</button>
        </div>
        <div class="bg-white dark:bg-slate-800 p-6 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm space-y-4">
            <h3 class="text-lg font-bold flex items-center gap-2"><i class="fa-solid fa-ranking-star text-amber-500"></i> En Uygun Tedarikçiler (Özet)</h3>
            <div class="overflow-x-auto">
                <table class="w-full text-left border-collapse">
                    <thead><tr class="bg-slate-50 dark:bg-slate-700/50 border-b border-slate-200 dark:border-slate-700 text-xs font-semibold text-slate-500 uppercase"><th class="p-3">Hammadde</th><th class="p-3">En Ucuz Tedarikçi</th><th class="p-3">Nakliye Dahil Fiyat</th><th class="p-3">Tarih</th></tr></thead>
                    <tbody class="divide-y divide-slate-200 dark:divide-slate-700 text-sm">
                        {% for c in comparisons %}
                        <tr class="bg-emerald-50/50 dark:bg-emerald-950/20">
                            <td class="p-3 font-medium">{{ c.material.name }} ({{ c.material.code }})</td>
                            <td class="p-3 font-bold text-emerald-700 dark:text-emerald-400"><i class="fa-solid fa-check-circle mr-1"></i> {{ c.supplier.name }}</td>
                            <td class="p-3 font-bold">{{ c.shipping_included | tr_num }} {{ c.currency }} / {{ c.material.unit }}</td>
                            <td class="p-3 text-slate-500 text-xs">{{ c.date }}</td>
                        </tr>
                        {% else %}
                        <tr><td colspan="4" class="p-4 text-center text-slate-500">Veri yok.</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        <div class="space-y-4">
            <div class="flex justify-between items-center">
                <h3 class="text-lg font-bold">Tüm Fiyat Kayıtları</h3>
                <form method="GET" class="flex gap-2">
                    <select name="material_id" onchange="this.form.submit()" class="px-3 py-1.5 border rounded-lg text-sm dark:bg-slate-700 dark:border-slate-600">
                        <option value="">Tüm Hammaddeler</option>
                        {% for m in materials %}<option value="{{ m.id }}" {{ 'selected' if request.args.get('material_id') == m.id|string }}>{{ m.name }}</option>{% endfor %}
                    </select>
                </form>
            </div>
            <div class="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden shadow-sm">
                <table class="w-full text-left border-collapse">
                    <thead><tr class="bg-slate-50 dark:bg-slate-700/50 border-b border-slate-200 dark:border-slate-700 text-xs font-semibold text-slate-500 uppercase"><th class="p-4">Tarih</th><th class="p-4">Hammadde</th><th class="p-4">Firma</th><th class="p-4">Birim Fiyat</th><th class="p-4">Nakliye Dahil</th><th class="p-4 text-right">İşlemler</th></tr></thead>
                    <tbody class="divide-y divide-slate-200 dark:divide-slate-700 text-sm">
                        {% for p in prices %}
                        <tr>
                            <td class="p-4 text-slate-500 text-xs">{{ p.date }}</td>
                            <td class="p-4 font-medium">{{ p.material.name }}</td>
                            <td class="p-4 text-slate-600 dark:text-slate-300">{{ p.supplier.name }}</td>
                            <td class="p-4">{{ p.unit_price | tr_num }} {{ p.currency }}</td>
                            <td class="p-4 font-bold text-blue-600">{{ p.shipping_included | tr_num }} {{ p.currency }}</td>
                            <td class="p-4 text-right">{% if session.get('role') in ['admin', 'yonetici'] %}<a href="{{ url_for('delete_price', id=p.id) }}" onclick="return confirm('Emin misiniz?')" class="text-rose-600 text-xs">Sil</a>{% endif %}</td>
                        </tr>
                        {% else %}
                        <tr><td colspan="6" class="p-6 text-center text-slate-500">Kayıt bulunamadı.</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        <div x-show="openAdd" class="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50" style="display: none;" x-data="{ shippingType: 'per_unit', unitPrice: 0, shippingCost: 0 }">
            <div class="bg-white dark:bg-slate-800 p-6 rounded-xl max-w-lg w-full shadow-lg" @click.outside="openAdd = false">
                <h3 class="text-lg font-bold mb-4">Yeni Fiyat Ekle</h3>
                <form action="{{ url_for('add_price') }}" method="POST" class="space-y-4">
                    <div class="grid grid-cols-2 gap-4">
                        <div><label class="block text-sm font-medium mb-1">Hammadde</label><select name="material_id" required class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600">{% for m in materials %}<option value="{{ m.id }}">{{ m.name }}</option>{% endfor %}</select></div>
                        <div><label class="block text-sm font-medium mb-1">Firma</label><select name="supplier_id" required class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600">{% for s in suppliers %}<option value="{{ s.id }}">{{ s.name }}</option>{% endfor %}</select></div>
                    </div>
                    <div class="grid grid-cols-3 gap-4">
                        <div><label class="block text-sm font-medium mb-1">Tarih</label><input type="date" name="date" value="{{ datetime.now().strftime('%Y-%m-%d') }}" required class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></div>
                        <div><label class="block text-sm font-medium mb-1">Para Birimi</label><select name="currency" class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"><option value="TL">TL</option><option value="USD">USD</option><option value="EUR">EUR</option></select></div>
                        <div><label class="block text-sm font-medium mb-1">Birim Fiyat</label><input type="number" step="0.01" name="unit_price" x-model.number="unitPrice" required class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></div>
                    </div>
                    <div class="grid grid-cols-2 gap-4">
                        <div><label class="block text-sm font-medium mb-1">Nakliye Tipi</label><select name="shipping_type" x-model="shippingType" class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"><option value="per_unit">Birim Başına</option><option value="per_shipment">Toplam Sevkiyat</option></select></div>
                        <div><label class="block text-sm font-medium mb-1">Nakliye Ücreti</label><input type="number" step="0.01" name="shipping_cost" x-model.number="shippingCost" value="0" class="w-full px-3 py-2 border rounded-lg dark:bg-slate-700 dark:border-slate-600"></div>
                    </div>
                    <div class="flex justify-end gap-2"><button type="button" @click="openAdd = false" class="px-4 py-2 bg-slate-200 dark:bg-slate-700 rounded-lg text-sm">İptal</button><button type="submit" class="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm">Kaydet</button></div>
                </form>
            </div>
        </div>
    </div>
    """,
      prices=prices_list,
      comparisons=comparisons,
      materials=materials,
      suppliers=suppliers,
      datetime=datetime,
  )


@app.route("/prices/add", methods=["POST"])
@login_required
def add_price():
  if session.get("status") != "active":
    return redirect(url_for("index"))

  unit_price = float(request.form.get("unit_price") or 0)
  shipping_cost = float(request.form.get("shipping_cost") or 0)
  shipping_type = request.form.get("shipping_type")

  shipping_excluded = unit_price
  shipping_included = unit_price + shipping_cost

  p = Price(
      material_id=request.form.get("material_id"),
      supplier_id=request.form.get("supplier_id"),
      date=request.form.get("date"),
      currency=request.form.get("currency"),
      unit_price=unit_price,
      shipping_type=shipping_type,
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
