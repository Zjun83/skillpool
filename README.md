# SkillPool v4.1.0

> Skill registry, search, and management API built with FastAPI.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
python -m skillpool.main

# API available at http://localhost:8000
# Docs at http://localhost:8000/docs
```

## Docker

```bash
# Build and run
docker compose -f deploy/docker-compose.yml up -d

# Health check
curl http://localhost:8000/health
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/api/v1/skills` | List all skills |
| POST | `/api/v1/skills` | Register a new skill |
| GET | `/api/v1/skills/{skill_id}` | Get skill by ID |
| PUT | `/api/v1/skills/{skill_id}` | Update a skill |
| DELETE | `/api/v1/skills/{skill_id}` | Delete a skill |
| GET | `/api/v1/skills/search` | Search skills |

## Project Structure

```
skillpool/
├── skillpool/           # Application source
│   ├── __init__.py
│   ├── main.py          # FastAPI app entry point
│   ├── api/             # API routes
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       └── skills.py
│   ├── models/          # Pydantic models
│   │   ├── __init__.py
│   │   └── skill.py
│   ├── services/        # Business logic
│   │   ├── __init__.py
│   │   └── skill_service.py
│   └── config.py        # Configuration
├── deploy/              # Deployment configs
│   ├── Dockerfile
│   ├── deployment.yml   # Kubernetes manifest
│   └── docker-compose.yml
├── tests/               # Test suite
│   ├── __init__.py
│   ├── conftest.py
│   └── test_skills.py
├── requirements.txt
├── pyproject.toml
└── README.md
```

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `SKILLPOOL_HOST` | `0.0.0.0` | Server bind address |
| `SKILLPOOL_PORT` | `8000` | Server bind port |
| `SKILLPOOL_DATA_DIR` | `./data` | Data storage directory |
| `SKILLPOOL_LOG_LEVEL` | `INFO` | Logging level |

## License

MIT
