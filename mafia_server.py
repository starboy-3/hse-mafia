import logging
import queue
import threading
from collections import defaultdict
from concurrent import futures
from random import shuffle

import grpc

import grpc_protos.mafia_server_pb2 as mafia_server_pb2
import grpc_protos.mafia_server_pb2_grpc as mafia_server_grpc_pb2
from role_dto import Role, Person, Status

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

class Game:
    def __init__(self):
        self.cv = threading.Condition()
        self.notifications = {}
        self.user_id = 0
        self.id_to_info = defaultdict(Person)
        self.ready_counter = 0
        self.votes = dict()
        self.game_roles = [Role.MAFIA, Role.CIVILIAN, Role.CIVILIAN, Role.SHERIFF]
        shuffle(self.game_roles)
        self.end_game = False
        self.counter_killed_civilians = 0
        self.checked_role = None
        self.killed = None
        self.checked = None


class MafiaServer(mafia_server_grpc_pb2.MafiaServerServicer):
    def __init__(self):
        self.active_games = defaultdict(Game)

    def ResultedPersonVote(self, session):
        max_votes = max(self.active_games[session].votes.values())
        for idx, votes_amount in self.active_games[session].votes.items():
            if votes_amount == max_votes:
                return idx
        return None

    def SetUserName(self, request, context):
        try:
            logging.info("Setting user name: " + request.name)
            self.active_games[request.session].user_id += 1
            self.active_games[request.session].id_to_info[self.active_games[request.session].user_id].name = request.name
            connected_users = []
            for i in self.active_games[request.session].notifications:
                self.active_games[request.session].notifications[i].put((request.name, Status.CONNECTED))
                connected_users.append(self.active_games[request.session].id_to_info[i].name)
            self.active_games[request.session].notifications[self.active_games[request.session].user_id] = queue.Queue()
            logging.info("Connected users: " + ", ".join(connected_users))
        except Exception as e:
            logging.error(e)
        return mafia_server_pb2.ConnectedUsers(names=connected_users, id=self.active_games[request.session].user_id)

    def GetNotifications(self, request, context):
        logging.info(f"Subscribing: {request.id}, in session: {request.session}")
        logging.info(self.active_games[request.session].notifications)
        while True:
            if request.id not in self.active_games[request.session].notifications:
                continue
            first, second = self.active_games[request.session].notifications[request.id].get()
            if first == Status.DELETED:
                break
            yield mafia_server_pb2.NotificationsResponse(user_name=first, connected=(second == Status.CONNECTED))

    def DisconnectUser(self, request, context):
        self.active_games[request.session].notifications[request.id].put((None, Status.DELETED))
        del self.active_games[request.session].notifications[request.id]
        for elem in self.active_games[request.session].notifications:
            self.active_games[request.session].notifications[elem].put(
                (self.active_games[request.session].id_to_info[request.id].name, Status.DISCONNECTED))
        del self.active_games[request.session].id_to_info[request.id]
        return mafia_server_pb2.Empty()

    def SetReadyStatus(self, request, context):
        self.active_games[request.session].ready_counter += 1
        self.active_games[request.session].votes[request.id] = 0
        with self.active_games[request.session].cv:
            while self.active_games[request.session].ready_counter % 4 != 0:
                self.active_games[request.session].cv.wait()
            role = self.active_games[request.session].game_roles.pop()
            self.active_games[request.session].id_to_info[request.id].role = role
            self.active_games[request.session].cv.notify()
        return mafia_server_pb2.ReadyResponse(role=role.value,
                                              users=[elem.name for elem in self.active_games[request.session].id_to_info.values()],
                                              ids=self.active_games[request.session].id_to_info.keys())

    def EndDay(self, request, context):
        self.active_games[request.session].checked_role = None
        self.active_games[request.session].killed = None
        self.active_games[request.session].ready_counter += 1
        with self.active_games[request.session].cv:
            while self.active_games[request.session].ready_counter % 4 != 0:
                self.active_games[request.session].cv.wait()
            self.active_games[request.session].cv.notify_all()
        if self.active_games[request.session].id_to_info[self.ResultedPersonVote(request.session)].role == Role.MAFIA:
            return mafia_server_pb2.EndDayResponse(killed=self.ResultedPersonVote(request.session), end_game=True)
        self.active_games[request.session].id_to_info[self.ResultedPersonVote(request.session)].role = Role.KILLED
        return mafia_server_pb2.EndDayResponse(killed=self.ResultedPersonVote(request.session), end_game=False)

    def KillUserVote(self, request, context):
        self.active_games[request.session].votes[request.id] += 1
        return mafia_server_pb2.Empty()

    def SkipNight(self, request, context):
        self.active_games[request.session].ready_counter += 1
        with self.active_games[request.session].cv:
            while self.active_games[request.session].ready_counter % 4 != 0:
                self.active_games[request.session].cv.wait()
            self.active_games[request.session].cv.notify_all()
        return mafia_server_pb2.EndNightResponse(
            killed=self.active_games[request.session].killed,
            checked_role=self.active_games[request.session].checked_role.value,
            checked=self.active_games[request.session].checked,
            end_game=self.active_games[request.session].end_game
        )

    def KillMafiaUser(self, request, context):
        self.active_games[request.session].ready_counter += 1
        self.active_games[request.session].killed = request.id
        self.active_games[request.session].id_to_info[request.id].role = Role.KILLED
        counter = 0
        for elem in self.active_games[request.session].id_to_info.values():
            if elem.role == Role.CIVILIAN or elem.role == Role.SHERIFF:
                counter += 1
        if counter <= 1:
            self.active_games[request.session].end_game = True
        logging.info(self.active_games[request.session].ready_counter)
        with self.active_games[request.session].cv:
            while self.active_games[request.session].ready_counter % 4 != 0:
                self.active_games[request.session].cv.wait()
            self.active_games[request.session].cv.notify_all()
        return mafia_server_pb2.EndNightResponse(killed=self.active_games[request.session].killed,
                                                 checked_role=self.active_games[request.session].checked_role.value,
                                                 checked=self.active_games[request.session].checked,
                                                 end_game=self.active_games[request.session].end_game)

    def CheckUser(self, request, context):
        self.active_games[request.session].ready_counter += 1
        self.active_games[request.session].checked_role = self.active_games[request.session].id_to_info[request.id].role
        self.active_games[request.session].checked = request.id
        with self.active_games[request.session].cv:
            while self.active_games[request.session].ready_counter % 4 != 0:
                self.active_games[request.session].cv.wait()
            self.active_games[request.session].cv.notify_all()
        return mafia_server_pb2.EndNightResponse(killed=self.active_games[request.session].killed,
                                                 checked_role=self.active_games[request.session].checked_role.value,
                                                 checked=self.active_games[request.session].checked,
                                                 end_game=self.active_games[request.session].end_game)


if __name__ == '__main__':
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    mafia_server_grpc_pb2.add_MafiaServerServicer_to_server(MafiaServer(), server)
    listen_addr = '[::]:8080'
    server.add_insecure_port(listen_addr)
    server.start()
    server.wait_for_termination()
