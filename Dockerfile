FROM python:latest

WORKDIR /mafia
COPY . .
RUN python -m pip install --upgrade pip && python -m pip install -r requirements.txt

CMD [ "python", "mafia_server.py" ]