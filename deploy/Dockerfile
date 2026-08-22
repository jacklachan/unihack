# CALIPER on Hugging Face Spaces (Docker SDK).
#
# No requirements.txt: the pipeline and the console are standard library only,
# which is the whole point -- the image is a stock Python and the source, and
# nothing can break because a wheel moved.
FROM python:3.12-slim

# Spaces runs the container as uid 1000; HOME must be writable for the cache
# directory the LLM adapter uses.
RUN useradd -m -u 1000 caliper
WORKDIR /app

COPY --chown=caliper:caliper . /app

USER caliper
ENV HOME=/home/caliper \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=7860

# Enrich the sample catalogue at build time so the Space answers its first
# request with a populated console rather than an empty state. Judges who want
# to see it run can still upload their own file.
RUN python -m caliper run data/input/sample_1000_items.csv -o data/out \
 && python tests/test_core.py

EXPOSE 7860
CMD ["python", "-m", "caliper", "serve", "--host", "0.0.0.0", "--port", "7860", \
     "--no-browser", "-o", "data/out"]
