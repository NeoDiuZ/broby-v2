from pathlib import Path
from dotenv import load_dotenv
from alembic.config import Config
from alembic import command
root=Path(__file__).resolve().parents[1]
load_dotenv(root.parent/'.env')
if __name__=='__main__':command.upgrade(Config(str(root/'alembic.ini')),'head')
