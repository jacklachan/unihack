"""Set an API key in .env without exposing it in shell history.

    python set_key.py            # prompts, input is hidden
    python set_key.py GEMINI     # choose a different provider
"""
import getpass, os, re, sys

PROV = {"GROQ": "GROQ_API_KEY", "GEMINI": "GEMINI_API_KEY",
        "ANTHROPIC": "ANTHROPIC_API_KEY", "OPENAI": "OPENAI_API_KEY"}
name = (sys.argv[1] if len(sys.argv) > 1 else "GROQ").upper()
var = PROV.get(name)
if not var:
    sys.exit("unknown provider {!r}; choose from {}".format(name, ", ".join(PROV)))

key = getpass.getpass("Paste {} (input hidden, then Enter): ".format(var)).strip()
if not key:
    sys.exit("nothing entered; .env unchanged")

lines = []
if os.path.exists(".env"):
    lines = [l.rstrip("\n") for l in open(".env", encoding="utf-8")]
lines = [l for l in lines if not re.match(r"\s*" + var + r"\s*=", l)]
if not any(l.startswith("#") for l in lines[:1]):
    lines.insert(0, "# CALIPER local secrets -- gitignored, never commit this file.")
lines.append("{}={}".format(var, key))
with open(".env", "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
print("{} written to .env ({} chars, starts {}...)".format(var, len(key), key[:4]))
