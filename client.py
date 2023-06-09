import random
import string
import threading
import grpc
import logging

import grpc_protos.mafia_server_pb2 as mafia_server_pb2
import grpc_protos.mafia_server_pb2_grpc as mafia_server_grpc_pb2
from role_dto import Role

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

r = random.Random()
BOT_NAME_LENGTH = 5

class Client:
    def __init__(self):
        self.player_ids = []
        self.is_bot = False
        self.name = None
        self.game_name = None
        self.role = None
        self.user_id = 0
        self.connected_players = []
        self.stub = None
        self.game_channel = grpc.insecure_channel('localhost:8080')
        self.notifications_channel = grpc.insecure_channel('localhost:8080')

    def set_night(self, alive):
        logging.info("Current phase is night")
        logging.info(f"Alive players: {alive}")
        if self.role == Role.KILLED or self.role == Role.CIVILIAN:
            response = self.stub.SkipNight(mafia_server_pb2.SkipNightRequest(session=self.game_name))
        elif self.role == Role.MAFIA:
            if self.is_bot:
                name_id = r.choice(self.player_ids)
            else:
                name_id = input_with_retries("Choose player to kill, write his id:", "Please enter id correctly", is_int=True)

            logging.info(f"Chosen player: {str(name_id)}")
            response = self.stub.KillMafiaUser(mafia_server_pb2.KillMafiaUserRequest(session=self.game_name, id=name_id))
        else:
            if self.is_bot:
                name_id = r.choice(self.player_ids)
            else:
                name_id = input_with_retries("Choose player to check, write his id:", "Please enter id correctly", is_int=True)

            logging.info(f"Chosen player: {str(name_id)}")
            response = self.stub.CheckUser(mafia_server_pb2.CheckUserRequest(session=self.game_name, id=name_id))

        logging.info("Night ended. Results of round: ")
        if self.role == Role.SHERIFF and response.checked_role:
            logging.info(f'{str(name_id)} is {str(response.checked_role)}')
        del alive[response.killed]
        logging.info(f"Killed: ", response.killed)
        if self.user_id == response.killed:
            logging.info("You were killed by majority decision")
        self.role = Role.KILLED
        if response.end_game:
            logging.info("Mafia won the game!")
            return
        self.set_day(alive)

    def set_day(self, alive):
        logging.info("Current phase is day")
        if self.role == Role.KILLED:
            response = self.stub.EndDay(mafia_server_pb2.EndDayRequest(session=self.game_name, id=self.user_id))
            del alive[response.killed]
            self.set_night(alive)
        logging.info(f"Alive players: {alive}")
        if self.is_bot:
            name_id = r.choice(self.player_ids)
        else:
            name_id = input_with_retries("Choose player id to vote for him, write id:", "Please write id correctly", is_int=True)
        logging.info(f"Chosen player: {name_id}")
        self.stub.KillUserVote(mafia_server_pb2.KillVoteRequest(session=self.game_name, id=name_id))
        logging.info("Press any key in all users to continue in all users")
        if not self.is_bot:
            input()
        response = self.stub.EndDay(mafia_server_pb2.EndDayRequest(session=self.game_name, id=self.user_id))
        if response.end_game:
            logging.info("\nCivilians won!\n")
            return
        del alive[response.killed]
        if self.user_id == response.killed:
            logging.info("You were killed by majority decision")
            self.role = Role.KILLED
        self.set_night(alive)

    def get_notifications(self):
        stub = mafia_server_grpc_pb2.MafiaServerStub(self.notifications_channel)
        try:
            for event in stub.GetNotifications(mafia_server_pb2.NotificationsRequest(id=self.user_id, session=self.game_name)):
                if event.connected:
                    logging.info(f"Connected: {event.user_name}")
                    self.connected_players.append(event.user_name)
                else:
                    logging.info(f"Disconnected: {event.user_name}")
                    self.connected_players.remove(event.user_name)
        except Exception as e:
            logging.error(e)
        self.notifications_channel.close()

    def start(self):
        player_mode = input_with_retries("Is this real user or bot: type 'b/bot' or 'r/real':", "Please pass correct mode", options=['bot', 'b', 'r', 'real'])
        self.is_bot = 'b' in player_mode.lower()
        if self.is_bot:
            name_field = randomword(BOT_NAME_LENGTH)
        else:
            logging.info("Enter your name: ")
            name_field = input()
        self.name = name_field
        stub = mafia_server_grpc_pb2.MafiaServerStub(self.game_channel)
        self.stub = stub
        logging.info("Enter name (id) of the game or create game passing id:")
        game_name = input()
        self.game_name = game_name
        response = stub.SetUserName(mafia_server_pb2.SetUserNameRequest(name=self.name, session=self.game_name))
        self.user_id = response.id
        self.connected_players = response.names
        th = threading.Thread(target=self.get_notifications, args=())
        th.start()
        while True:
            logging.info("Game will start only when 4 players are ready")
            if self.is_bot:
                command = 'r'
            else:
                input_msg = """
                Type R/r - ready for game in the room
                Type L/l - list online players
                Type D/d - disconnect from the game"""
                command = input_with_retries(input_msg,  "Unknown command. Please type command correctly", options=['d', 'l', 'r', 'D', 'R', 'L']).lower()

            if command == 'd':
                self.stub.DisconnectUser(mafia_server_pb2.DisconnectUserRequest(session=self.game_name, id=self.user_id))
                break
            elif command == 'l':
                logging.info(f"Connected players: {self.connected_players}")
            elif command == 'r':
                logging.info("Ok. You're ready for the game. Waiting for others")
                response = self.stub.SetReadyStatus(mafia_server_pb2.ReadyRequest(session=self.game_name, id=self.user_id))
                logging.info(f"Your role: {response.role}")
                self.role = response.role
                self.player_ids = response.ids
                self.set_day(dict(zip(response.ids, response.users)))
                break
            self.game_channel.close()

def randomword(length):
   letters = string.ascii_lowercase
   return ''.join(random.choice(letters) for i in range(length))

def input_with_retries(input_msg, error_msg, options=[], is_int=False):
    inp = None
    logging.info(input_msg)
    while inp == None:
        try:
            inp = input()
            if is_int:
                inp = int(inp)
                if len(options) > 0 and inp not in options:
                    raise Exception
            elif inp not in options:
                raise Exception
        except InterruptedError or KeyboardInterrupt:
            exit(0)
        except Exception:
            inp = None
            logging.error(error_msg)
    return inp


if __name__ == '__main__':
    client = Client()
    client.start()