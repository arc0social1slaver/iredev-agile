# Claude UI

## Requirements

- Node.js 18+
- Python 3.10+

---

## Backend

```bash
cd backend
python -m venv venv

# Mac / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env
python app.py
```

Runs at `http://localhost:8000`

Demo accounts:
- `demo@example.com` / `password123`
- `admin@example.com` / `admin123`

---

## Frontend

In a new terminal from the project root:

```bash
npm install
cp .env.example .env
npm run dev
```

Opens at `http://localhost:5173`