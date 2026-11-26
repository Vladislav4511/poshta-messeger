import os
from flask import Flask, render_template_string

app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Технический перерыв</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            background-color: #000000;
            color: #ffffff;
            height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            text-align: center;
            padding: 20px;
            overflow: hidden;
        }
        .pulse-text {
            font-size: clamp(1.5rem, 4vw, 3rem);
            font-weight: 600;
            letter-spacing: 0.05em;
            animation: pulse 2.2s infinite ease-in-out;
        }
        @keyframes pulse {
            0%, 100% {
                opacity: 1;
                transform: scale(1);
                text-shadow: 0 0 15px rgba(255, 255, 255, 0.6);
            }
            50% {
                opacity: 0.35;
                transform: scale(0.97);
                text-shadow: none;
            }
        }
    </style>
</head>
<body>
    <div class="pulse-text">Голубиная почта закрыта на технический перерыв</div>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
