# Deploying StockZone to PythonAnywhere

## Prerequisites

- A PythonAnywhere account (free tier works for initial setup)
- Your StockZone repo pushed to GitHub

---

## Step 1 — Open a Bash Console

Log into PythonAnywhere. From the Dashboard, click **Consoles** → **Bash** to open a terminal.

---

## Step 2 — Clone the Repository

```bash
git clone https://github.com/salsburysteaks/stockzone
```

This creates `/home/yourusername/stockzone/`.

---

## Step 3 — Create a Virtual Environment

```bash
mkvirtualenv stockzone --python=python3.11
```

This creates the virtualenv at `/home/yourusername/.virtualenvs/stockzone/` and activates it automatically. Your prompt will show `(stockzone)`.

---

## Step 4 — Install Dependencies

```bash
cd stockzone
pip install -r requirements.txt
```

---

## Step 5 — Configure settings.py

Edit `stockzone/settings.py` and make these three changes:

```python
DEBUG = False

ALLOWED_HOSTS = ['yourusername.pythonanywhere.com']

STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
```

Replace `yourusername` with your actual PythonAnywhere username. Make sure `import os` is at the top of the file (Django includes it by default).

If your app uses a `.env` file for secrets (e.g. `SECRET_KEY`, `DATABASE_URL`), create that file at `/home/yourusername/stockzone/.env` with the appropriate values before running the next steps.

---

## Step 6 — Run Migrations

```bash
python manage.py migrate
```

---

## Step 7 — Collect Static Files

```bash
python manage.py collectstatic
```

Type `yes` when prompted. Static files will be written to `staticfiles/`.

---

## Step 8 — Create the Web App

In the PythonAnywhere dashboard:

1. Go to the **Web** tab
2. Click **Add a new web app**
3. Click through the domain confirmation (use the free `yourusername.pythonanywhere.com` domain)
4. Select **Manual configuration**
5. Select **Python 3.11**

Do not choose "Django" from the framework list — manual configuration gives you full control.

---

## Step 9 — Set the Source Code Directory

On the Web tab, under **Code**, set:

- **Source code:** `/home/yourusername/stockzone`
- **Working directory:** `/home/yourusername/stockzone`

---

## Step 10 — Edit the WSGI File

On the Web tab, click the link to your **WSGI configuration file** (something like `/var/www/yourusername_pythonanywhere_com_wsgi.py`).

Clear all existing content and replace it with:

```python
import os
import sys

path = '/home/yourusername/stockzone'
if path not in sys.path:
    sys.path.insert(0, path)

os.environ['DJANGO_SETTINGS_MODULE'] = 'stockzone.settings'

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

Replace `yourusername` with your actual username. Save the file.

---

## Step 11 — Set the Virtualenv Path

On the Web tab, under **Virtualenv**, enter:

```
/home/yourusername/.virtualenvs/stockzone
```

---

## Step 12 — Add Static Files Mapping

On the Web tab, under **Static files**, add a new entry:

| URL | Directory |
|-----|-----------|
| `/static/` | `/home/yourusername/stockzone/staticfiles/` |

---

## Step 13 — Schedule the Daily Pick Resolution

Go to the **Tasks** tab. Under **Scheduled tasks**, add a new daily task set to run after market close (e.g. 6:00 PM ET = 23:00 UTC):

```bash
/home/yourusername/.virtualenvs/stockzone/bin/python /home/yourusername/stockzone/manage.py resolve_picks
```

Use the full path to the virtualenv Python so the task runs with the correct environment regardless of which shell is active.

---

## Step 14 — Reload and Verify

Back on the **Web** tab, click the green **Reload** button.

Visit `https://yourusername.pythonanywhere.com` — the app should be live.

If you see a 500 error, check the **Error log** link on the Web tab for the traceback.

---

## Updating the App

When you push new changes to GitHub, pull and reload:

```bash
cd ~/stockzone
git pull
python manage.py migrate        # only if there are new migrations
python manage.py collectstatic  # only if static files changed
```

Then hit **Reload** on the Web tab.
