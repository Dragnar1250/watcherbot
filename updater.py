"""TürkBot otomatik güncelleyici.

baslat.bat bunu botu her başlatmadan önce çalıştırır. GitHub'daki depoda yeni bir sürüm varsa indirir,
kontrol eder ve kurar. Yeni sürüm bozuksa kurmaz; kurulduktan sonra bot açılamıyorsa eski sürüme geri döner.

Sadece Python'un kendi kütüphanelerini kullanır, git kurmaya gerek yoktur.
Ayarlar .env dosyasından okunur:
    GUNCELLEME_DEPO=kullaniciadi/depoadi   (boşsa güncelleme kapalıdır)
    GUNCELLEME_DALI=main
    GITHUB_TOKEN=                           (sadece gizli depo için)
    OTOMATIK_GUNCELLEME=1
"""
import io
import json
import re
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
STATE_FILE = os.path.join(DATA, "guncelleme.json")
SETTINGS_FILE = os.path.join(DATA, "guncelleme_ayar.json")   # Discord'dan /guncelle depo: ile yazılır
BACKUP = os.path.join(DATA, "yedek")

# Güncellemenin ASLA dokunmadığı yerler: ayarlar, veriler, Python ortamı, log, çalışan başlatıcı
KORUNAN = {".env", "data", ".venv", "bot.log", "baslat.bat", "__pycache__", ".git", ".github"}
GEREKLI = ["main.py", os.path.join("cogs", "__init__.py"), os.path.join("utils", "__init__.py")]
MAX_DENEME = 2  # yeni sürüm bu kadar başlatmada açılamazsa eskiye dönülür


def log(msg: str):
    print(f"[Güncelleme] {msg}", flush=True)


# ---------------- ayarlar ve durum ----------------
def read_env() -> dict:
    env = {}
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env


REPO_DESEN = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")


def parse_repo(text: str) -> str | None:
    """'kullanici/depo', 'github.com/kullanici/depo' ya da tam linki 'kullanici/depo' yapar."""
    t = text.strip()
    t = re.sub(r"^(https?://)?(www\.)?github\.com/", "", t, flags=re.I)
    t = t.strip("/")
    if t.lower().endswith(".git"):
        t = t[:-4]
    t = "/".join(t.split("/")[:2])
    return t if REPO_DESEN.match(t) else None


def saved_settings() -> dict:
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_repo(repo: str | None):
    os.makedirs(DATA, exist_ok=True)
    s = saved_settings()
    if repo:
        s["repo"] = repo
    else:
        s.pop("repo", None)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def config() -> dict:
    env = read_env()
    # .env'deki ayar önceliklidir; yoksa Discord'dan kaydedilen kullanılır
    repo = env.get("GUNCELLEME_DEPO", "").strip().strip("/") or saved_settings().get("repo", "")
    return {
        "repo": repo,
        "branch": env.get("GUNCELLEME_DALI", "main").strip() or "main",
        "token": env.get("GITHUB_TOKEN", "").strip(),
        "auto": env.get("OTOMATIK_GUNCELLEME", "1").strip() != "0",
        "api": os.getenv("GUNCELLEME_API", "https://api.github.com").rstrip("/"),
    }


def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            s = json.load(f)
    except (OSError, ValueError):
        s = {}
    s.setdefault("sha", None)
    s.setdefault("onceki_sha", None)
    s.setdefault("kotu", [])
    s.setdefault("bekleyen", False)
    s.setdefault("deneme", 0)
    s.setdefault("tarih", None)
    s.setdefault("mesaj", None)
    return s


def save_state(s: dict):
    os.makedirs(DATA, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


def mark_ok():
    """Bot başarıyla açılınca çağrılır: yeni sürüm sağlam."""
    s = load_state()
    if s["bekleyen"] or s["deneme"]:
        s["bekleyen"] = False
        s["deneme"] = 0
        save_state(s)


# ---------------- GitHub ----------------
def _get(url: str, cfg: dict, accept: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "TurkBot-Guncelleyici"})
    if cfg["token"]:
        req.add_header("Authorization", f"Bearer {cfg['token']}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def remote_info(cfg: dict) -> dict | None:
    """Daldaki son sürümün kimliğini (sha), tarihini ve açıklamasını döner. Ulaşılamazsa None."""
    if not cfg["repo"]:
        return None
    try:
        data = json.loads(_get(f"{cfg['api']}/repos/{cfg['repo']}/commits/{cfg['branch']}", cfg,
                               "application/vnd.github+json"))
        commit = data.get("commit", {})
        return {"sha": data["sha"], "tarih": commit.get("committer", {}).get("date"),
                "mesaj": (commit.get("message") or "").split("\n")[0][:200]}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            log("Depo bulunamadı. GUNCELLEME_DEPO doğru mu? Gizli depoysa GITHUB_TOKEN gerekli.")
        elif e.code in (401, 403):
            log(f"GitHub erişimi reddedildi ({e.code}). GITHUB_TOKEN'ı kontrol et.")
        else:
            log(f"GitHub hatası: {e.code}")
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        log(f"GitHub'a ulaşılamadı ({type(e).__name__}). Güncelleme atlandı.")
    return None


def update_available(cfg: dict | None = None) -> dict | None:
    """Kurulmaya uygun yeni sürüm varsa bilgisini döner."""
    cfg = cfg or config()
    info = remote_info(cfg)
    if info is None:
        return None
    s = load_state()
    if info["sha"] == s["sha"] or info["sha"] in s["kotu"]:
        return None
    return info


# ---------------- dosya işlemleri ----------------
def _managed_files(base: str) -> list[str]:
    """Güncellemenin yönettiği dosyalar (göreli yol)."""
    out = []
    for dirpath, dirnames, filenames in os.walk(base):
        rel_dir = os.path.relpath(dirpath, base)
        top = rel_dir.split(os.sep)[0]
        if top in KORUNAN:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in KORUNAN]
        for fn in filenames:
            rel = os.path.normpath(os.path.join(rel_dir, fn))
            if rel.split(os.sep)[0] in KORUNAN or fn.endswith((".pyc", ".tmp")):
                continue
            out.append(rel)
    return out


def _find_root(extracted: str) -> str | None:
    """Zip içinde main.py'nin olduğu klasörü bulur (depo kökü ya da bir alt klasör olabilir)."""
    for dirpath, dirnames, filenames in os.walk(extracted):
        if "main.py" in filenames and "cogs" in dirnames and "utils" in dirnames:
            return dirpath
    return None


def _validate(src: str) -> str | None:
    """Yeni sürüm kurulabilir mi? Sorun varsa açıklaması döner."""
    for req in GEREKLI:
        if not os.path.exists(os.path.join(src, req)):
            return f"Eksik dosya: {req}"
    for rel in _managed_files(src):
        if rel.endswith(".py"):
            path = os.path.join(src, rel)
            try:
                with open(path, encoding="utf-8") as f:
                    compile(f.read(), path, "exec")   # sadece söz dizimi kontrolü, dosya yazmaz
            except (SyntaxError, UnicodeDecodeError, ValueError) as e:
                line = getattr(e, "lineno", None)
                return f"Kod hatası: {rel}" + (f" (satır {line})" if line else "") + f": {e.__class__.__name__}"
    return None


def _copy_tree(src: str, dst: str, files: list[str]):
    for rel in files:
        s, d = os.path.join(src, rel), os.path.join(dst, rel)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(s, d)


def _read(path: str) -> bytes | None:
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def install(cfg: dict, info: dict) -> bool:
    """Yeni sürümü indirip kurar. Başarılıysa True."""
    s = load_state()
    sha = info["sha"]
    log(f"Yeni sürüm bulundu: {sha[:7]} — {info.get('mesaj') or ''}")
    try:
        blob = _get(f"{cfg['api']}/repos/{cfg['repo']}/zipball/{sha}", cfg, "application/vnd.github+json", timeout=120)
    except (urllib.error.URLError, OSError) as e:
        log(f"İndirilemedi ({type(e).__name__}). Sonra tekrar denenecek.")
        return False

    with tempfile.TemporaryDirectory() as tmp:
        try:
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                for name in z.namelist():   # zip içinden klasör dışına yazma girişimine karşı
                    target = os.path.realpath(os.path.join(tmp, name))
                    if not target.startswith(os.path.realpath(tmp) + os.sep) and target != os.path.realpath(tmp):
                        log("İndirilen sürümde güvensiz dosya yolu var. KURULMADI.")
                        s["kotu"].append(sha)
                        save_state(s)
                        return False
                z.extractall(tmp)
        except zipfile.BadZipFile as e:
            log(f"İndirilen dosya bozuk ({e}). Sonra tekrar denenecek.")
            return False
        src = _find_root(tmp)
        if src is None:
            log("Depoda main.py, cogs ve utils bulunamadı. Atlandı.")
            s["kotu"].append(sha)
            save_state(s)
            return False
        problem = _validate(src)
        if problem:
            log(f"Yeni sürüm KURULMADI, çünkü bozuk: {problem}")
            s["kotu"].append(sha)
            save_state(s)
            return False

        new_files = _managed_files(src)
        old_req = _read(os.path.join(ROOT, "requirements.txt"))

        # Yedek al
        if os.path.isdir(BACKUP):
            shutil.rmtree(BACKUP)
        os.makedirs(BACKUP)
        _copy_tree(ROOT, BACKUP, _managed_files(ROOT))

        _copy_tree(src, ROOT, new_files)

        # baslat.bat çalışırken değiştirilemez, yeni hali yanına bırakılır
        new_bat = os.path.join(src, "baslat.bat")
        if os.path.exists(new_bat) and _read(new_bat) != _read(os.path.join(ROOT, "baslat.bat")):
            shutil.copy2(new_bat, os.path.join(ROOT, "baslat.bat.yeni"))
            log("baslat.bat için yeni bir sürüm var: baslat.bat.yeni (botu kapatıp elle değiştirebilirsin).")

    if _read(os.path.join(ROOT, "requirements.txt")) != old_req:
        log("Kütüphaneler güncelleniyor...")
        subprocess.call([sys.executable, "-m", "pip", "install", "-q", "-r", os.path.join(ROOT, "requirements.txt")])

    s["onceki_sha"] = s["sha"]
    s["sha"] = sha
    s["tarih"] = info.get("tarih")
    s["mesaj"] = info.get("mesaj")
    s["bekleyen"] = True
    s["deneme"] = 0
    save_state(s)
    log(f"Kuruldu: {sha[:7]}")
    return True


def rollback(reason: str):
    s = load_state()
    if not os.path.isdir(BACKUP):
        log("Geri dönülecek yedek yok.")
        s["bekleyen"] = False
        save_state(s)
        return
    _copy_tree(BACKUP, ROOT, _managed_files(BACKUP))
    if s["sha"]:
        s["kotu"].append(s["sha"])
    log(f"Yeni sürüm ({(s['sha'] or '?')[:7]}) {reason}. Eski sürüme geri dönüldü.")
    s["sha"] = s["onceki_sha"]
    s["onceki_sha"] = None
    s["bekleyen"] = False
    s["deneme"] = 0
    save_state(s)


def startup():
    """baslat.bat her döngüde, botu açmadan önce bunu çalıştırır."""
    cfg = config()
    s = load_state()
    # Son kurulan sürüm bot açılamadan çöktüyse say; sınır aşılırsa eskiye dön
    if s["bekleyen"]:
        s["deneme"] += 1
        save_state(s)
        if s["deneme"] > MAX_DENEME:
            rollback(f"{MAX_DENEME} denemede açılamadı")
            return
    if not cfg["repo"] or not cfg["auto"]:
        return
    if s["bekleyen"]:
        return  # yeni sürüm henüz denenmekte, üstüne yenisini kurma
    info = update_available(cfg)
    if info:
        install(cfg, info)


if __name__ == "__main__":
    try:
        startup()
    except Exception as e:  # güncelleyici asla botun açılmasını engellemesin
        log(f"Beklenmeyen hata, güncelleme atlandı: {type(e).__name__}: {e}")
    sys.exit(0)
