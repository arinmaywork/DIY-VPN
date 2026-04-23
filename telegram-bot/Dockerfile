# DIY-VPN Telegram bot container
# Runs python-telegram-bot + flyctl (for ssh-exec into the VPN machine).

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLYCTL_INSTALL=/root/.fly \
    PATH=/root/.fly/bin:$PATH

# Runtime deps: curl (to install flyctl), ca-certificates, ssh client
# (flyctl's `ssh console` needs an ssh binary on PATH to exec commands)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      curl \
      ca-certificates \
      openssh-client \
 && rm -rf /var/lib/apt/lists/*

# Install flyctl (latest stable)
RUN curl -fsSL https://fly.io/install.sh | sh \
 && /root/.fly/bin/flyctl version

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .
COPY lib ./lib

# Health: the bot's only "liveness" is the polling loop. No HTTP port needed.
# Fly will restart the machine if the process exits.

CMD ["python", "-u", "bot.py"]
