# CALIPER as a container, for hosts other than Hugging Face.
#
# This image deliberately does NOT install requirements.txt. That file exists for
# the Gradio front end on Hugging Face; this container runs the stdlib web
# console instead, so the image is a stock Python plus the source and nothing can
# break because a wheel moved. See deploy/DEPLOY.md.
FROM python:3.12-slim

# Most container hosts run as a non-root uid; HOME must be writable for the
# cache directory the LLM adapter uses.
RUN useradd -m -u 1000 caliper
WORKDIR /app

COPY --chown=caliper:caliper . /app

USER caliper
ENV HOME=/home/caliper \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=7860

# Enrich the sample catalogue at build time so the first request is answered by
# a populated console rather than an empty state, and fail the build if any
# invariant test breaks.
RUN python -m caliper run data/input/sample_1000_items.csv -o data/out \
 && python tests/test_core.py

EXPOSE 7860
CMD ["python", "-m", "caliper", "serve", "--host", "0.0.0.0", "--port", "7860", \
     "--no-browser", "-o", "data/out"]
