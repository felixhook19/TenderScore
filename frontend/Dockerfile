# Development image for the web service (Vite dev server).
FROM node:22-slim

# Some development environments sit behind a TLS-intercepting proxy. An extra
# root CA may be supplied at build time; empty by default and never required.
ARG EXTRA_CA_CERT=""
RUN mkdir -p /usr/local/share/ca-certificates \
    && printf '%s\n' "$EXTRA_CA_CERT" > /usr/local/share/ca-certificates/extra-ca.crt
ENV NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/extra-ca.crt

WORKDIR /srv/frontend

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
