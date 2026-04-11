## Requirements

- Python 3.10+

---

## Backend

```bash
python -m venv venv

# Mac / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env

python -m src.server.app
```

Runs at `http://localhost:8000`