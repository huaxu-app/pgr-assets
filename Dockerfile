FROM python:slim AS build
LABEL authors="nova"

RUN apt-get -qq update && \
    apt-get -yqq --no-install-recommends install \
      build-essential git

RUN python -m venv /opt/venv
# Make sure we use the virtualenv:
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

FROM python:slim AS publish
RUN apt-get -qq update && apt-get -yqq install --no-install-recommends ffmpeg

COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"


WORKDIR /app
COPY . .

ENTRYPOINT ["python", "pgr-assets.py", "--output", "/out"]
