# Create a belief state that tracks possible  board states using particle filtering and observations

import config
from observation import Observation
import chess, random

class beliefState:
    def __init__(self, numParticles=100):
        self.numParticles = numParticles
        self.particles = []     #Particles for the almighty particle filter 
        self.Computercolor = not config.PLAYER_COLOR

        #Keep track of captured pieces so that guesstimation is more estimation than guessing
        self.capturedPieces = {
            chess.PAWN: 0,
            chess.ROOK: 0,
            chess.KNIGHT: 0,
            chess.BISHOP: 0,
            chess.QUEEN: 0,
            chess.KING: 0
        }


    #Called once at start of game
    def generateParticles(self):
        self.particles = []
        for particle in range(self.numParticles):
            newParticleBoard = chess.Board()  #Start with a standard chess board populated with pieces in initial positon
            self.particles.append(newParticleBoard)

    def updateParticles(self, observation):
        newParticles = []

        #Remove particles that aren't consistent with the observation
        for particle in self.particles:
            if self.isConsistent(particle, observation):
                newParticles.append(particle)
        
        #Guesstimate new particles if less than num particles
        if len(newParticles) < self.numParticles:
            while len(newParticles) < self.numParticles:
                newParticles.append(self.guesstimate(observation)) 

        self.particles = newParticles #update :D

    def isConsistent(self, particle, observation):
        for square in observation.visibleSquares:
            piece = particle.piece_at(square)
            if piece != observation.visiblePieces.get(square, None):
                return False
        
        return True
    
    #Guesstimate the board state, all frienly pieces and visible enemy pieces should not be random
    def guesstimate(self, observation):
        board = chess.Board()
        board.clear_board()

        #Keep track of what pieces have been observed so that the guessing isnt comlpetely random
        enemyPieces = { 
            chess.PAWN: 8 - self.capturedPieces[chess.PAWN],
            chess.ROOK: 2 - self.capturedPieces[chess.ROOK],
            chess.KNIGHT: 2 - self.capturedPieces[chess.KNIGHT],
            chess.BISHOP: 2 - self.capturedPieces[chess.BISHOP],
            chess.QUEEN: 1 - self.capturedPieces[chess.QUEEN],
            chess.KING: 1
        }

        for square, piece in observation.visiblePieces.items():
            if piece.color == self.Computercolor:
                board.set_piece_at(square, piece) #Set all friendly pieces to their observed position
            else:
                board.set_piece_at(square, piece) #Set all visible enemy pieces to their observed position
                enemyPieces[piece.piece_type] -= 1 #Decrement the count of that piece type that is left to be placed

        #Randomly generate board in non observable areas
        #If there are no hidden pieces, dont place any
        if any(count > 0 for count in enemyPieces.values()):    
            for square in chess.SQUARES:
                if square not in observation.visibleSquares:
                    if random.random() > .90:
                        availablePieces = {p: c for p, c in enemyPieces.items() if c > 0}
                        if not availablePieces:
                            break
                        pieceType = random.choices(list(enemyPieces.keys()), weights=enemyPieces.values())[0] #Randomly select a piece type to place based on how many of each piece type are left to be placed
                        if enemyPieces[pieceType] > 0: #If there are still pieces of that type left to be placed
                            board.set_piece_at(square, chess.Piece(pieceType, config.PLAYER_COLOR)) #Place the piece on the board
                            enemyPieces[pieceType] -= 1 #Decrement the count of that piece type that is left to be placed

        #ensure that there is a king
        if not board.king(config.PLAYER_COLOR):
            emptySquares = [square for square in chess.SQUARES if not board.piece_at(square)]
            if emptySquares:
                board.set_piece_at(random.choice(emptySquares), chess.Piece(chess.KING, config.PLAYER_COLOR))
            else:
                # If there are no empty squares, randomly replace a piece with the king
                randomSquare = random.choice(chess.SQUARES)
                board.set_piece_at(randomSquare, chess.Piece(chess.KING, config.PLAYER_COLOR))

        return board