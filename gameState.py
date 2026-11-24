
import random

import config
import chess
from observation import Observation
from engine import FogEngine

#File for running game operations. This will handle things like the board state and interacting with the chessAPI

class gameState:

    #gamestate is a state of the board currently
    def __init__(self, board : chess.Board = None):
        self.board = (board or chess.Board()).copy()
        self.turn = self.board.turn

        #Bad code, needs to be child of board
        self.winner = None # 'white' or 'black'
        self.draw = False

        # The computer only ever learns about the board through what it can observe, the same as the player
        self.computerColor = not config.PLAYER_COLOR
        self.engine = FogEngine(self.computerColor, thinkTime=config.ENGINE_THINK_TIME, numSamples=config.ENGINE_SAMPLES)
        self.beliefState = self.engine.belief

    # Ret True or False (game not over)
    def isGameOver(self):
        return self.board.is_game_over()


    #############################
    #   Computer Move
    #############################

    # Sunfish scores moves across boards sampled from the histogram belief state (see engine.py)
    def getSunfishMove(self):
        legalMoves = list(self.board.legal_moves)
        suggestions = self.engine.suggest(restrictTo=legalMoves)

        for suggestion in suggestions:
            print(f"  {suggestion.label:8} score {suggestion.score:7.1f}  votes {suggestion.votes}  king risk {suggestion.kingLoss}/{suggestion.samples}")

        #The engine plays by fog of war rules (no check) so double check the move is legal in this game
        for suggestion in suggestions:
            if suggestion.move in legalMoves:
                return suggestion.move
        print("No legal suggestion, random move made")
        return random.choice(legalMoves)


    #############################
    #   Observation Access
    #############################

    def getObservation(self, color):
        return Observation(self.board, color)

    def computerObservation(self):
        observation = self.getObservation(self.computerColor)
        enemies = {square: piece.piece_type for square, piece in observation.visiblePieces.items() if piece.color != self.computerColor}
        return observation, enemies

    #############################
    #   Belief State Access
    #############################

    #Player has moved: tell the engine what the computer can now see, and which of its pieces were taken
    def updateBeliefState(self):
        if not self.board.move_stack:
            return  #Computer is white and nothing has been played yet
        observation, enemies = self.computerObservation()
        capturedOwn = [square for square in self.engine.ownSquares() if self.board.color_at(square) != self.computerColor]
        self.engine.applyOpponentMove(enemies, capturedOwn, visibleOverride=observation.visibleSquares)

    #Computer has moved: record the move, then look at what the move uncovered
    def propagateComputerMove(self, computerMove):
        self.engine.applyOurMove(computerMove)
        observation, enemies = self.computerObservation()
        self.engine.applySightings(enemies, visibleOverride=observation.visibleSquares)
