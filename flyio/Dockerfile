# DIY-VPN container for Fly.io
# Bundles: Xray-core (VLESS+Reality) + Hysteria2 (QUIC) on Alpine
# Both protocols run on port 443 (TCP for Reality, UDP for Hysteria2)

FROM alpine:3.20

# ─── Build deps + runtime deps ────────────────────────────────────────────────
RUN apk add --no-cache \
      bash \
      ca-certificates \
      curl \
      jq \
      openssl \
      python3 \
      tini \
      tzdata \
      unzip \
      wget

# ─── Install Xray-core (latest stable from XTLS/Xray-core) ───────────────────
RUN set -eux; \
    case "$(uname -m)" in \
      x86_64)  XARCH="64" ;; \
      aarch64) XARCH="arm64-v8a" ;; \
      *) echo "unsupported arch"; exit 1 ;; \
    esac; \
    LATEST_TAG="$(curl -fsSL https://api.github.com/repos/XTLS/Xray-core/releases/latest | jq -r .tag_name)"; \
    curl -fsSL "https://github.com/XTLS/Xray-core/releases/download/${LATEST_TAG}/Xray-linux-${XARCH}.zip" -o /tmp/xray.zip; \
    unzip -q /tmp/xray.zip -d /tmp/xray; \
    install -m 0755 /tmp/xray/xray /usr/local/bin/xray; \
    install -d /usr/local/share/xray; \
    cp -r /tmp/xray/geoip.dat /tmp/xray/geosite.dat /usr/local/share/xray/ 2>/dev/null || true; \
    rm -rf /tmp/xray /tmp/xray.zip; \
    /usr/local/bin/xray version

# ─── Install Hysteria2 (latest stable from apernet/hysteria) ─────────────────
RUN set -eux; \
    case "$(uname -m)" in \
      x86_64)  HARCH="amd64" ;; \
      aarch64) HARCH="arm64" ;; \
      *) echo "unsupported arch"; exit 1 ;; \
    esac; \
    LATEST_TAG="$(curl -fsSL https://api.github.com/repos/apernet/hysteria/releases/latest | jq -r .tag_name)"; \
    curl -fsSL "https://github.com/apernet/hysteria/releases/download/${LATEST_TAG}/hysteria-linux-${HARCH}" -o /usr/local/bin/hysteria; \
    chmod 0755 /usr/local/bin/hysteria; \
    /usr/local/bin/hysteria version

# ─── App scaffolding ─────────────────────────────────────────────────────────
RUN mkdir -p /etc/xray /etc/hysteria /etc/templates /data
COPY config-templates/xray.json.template     /etc/templates/xray.json.template
COPY config-templates/hysteria2.yaml.template /etc/templates/hysteria2.yaml.template
COPY entrypoint.sh                            /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Expose service ports (informational; Fly's fly.toml is what actually opens them)
EXPOSE 443/tcp 443/udp

# tini = proper signal handling so SIGTERM from Fly cleanly shuts down both procs
ENTRYPOINT ["/sbin/tini", "--", "/entrypoint.sh"]
