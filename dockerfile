FROM python:3.14

WORKDIR /app
COPY ./bot /app

ARG INSTALL_NODE=false
RUN if [ "$INSTALL_NODE" = "true" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends nodejs npm \
        && rm -rf /var/lib/apt/lists/*; \
    fi

RUN pip install -r requirements.txt

CMD ["python3", "./main.py"]
