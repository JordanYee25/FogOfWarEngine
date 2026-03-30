
import config
from observation import Observation
import chess, random

#This belief state tracks possible board states using a probability matrix and observations

class beliefState:
    def __init__(self):
        self.color = not config.PLAYER_COLOR

        #Pieces marked by their file and piece type
        self.numPiecesPerType = {
            "Pawn" : 8,
            "Rook" : 2,
            "Knight" : 2,
            "Bishop" : 2,
            "Queen" : 1,
            "King" : 1
        }

        #Probabilities for Pawns,Rooks, Knights are union meaning that it doesnt matter which pawn is which
        #Reduces complexity. Except for Biishops since they are inherently on different squares and cannot overlap 
        # Each array for each piece is a length 64 array represeneting each squre on a chess board, with 0 being A1, 64 H8
        # Each square holds a probability less than 1, so each index is a float
        self.pieces = {
            "Pawns" : [],
            "Rooks" : [],
            "Knights" : [],
            "BishopLight" : [],
            "BishopDark" : [],
            "Queen" : [],
            "King" : []
        }

        self.generateDistributions()

    def generateDistributions(self):
        for piece in self.pieces:
            self.pieces[piece] = [0.0] * 64

        

    def predicitonStep(self, piece):

    def observationStep(self, piece):
