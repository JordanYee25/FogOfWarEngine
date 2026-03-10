import chess
import random
import config

class Particle:

    def __init__(self, board=None):
        self.board = None
        if board is None:
            self.board = chess.Board()
        else:
            self.board = board.copy()

        
    def isConsistent(self, observation):

        for square, piece in observation.visiblePieces.items():
            if self.board.piece_at(square) != piece:
                # print(f"Observation visible pieces: {len(observation.visiblePieces)}")
                # print(f"Observation visible squares: {len(observation.visibleSquares)}")
                return False
        return True
    
    # Update particle board one timestep (one chess move) using random next move for each particle ufor player move, and computer move for computer move
    # Proagation will  happen twice for a computer turn, one for the player and again for the known computer move
    def propagate(self, computerMove = None):
        if computerMove:
            self.board.turn = not config.PLAYER_COLOR
            if computerMove in self.board.legal_moves:
                self.board.push(computerMove)
                return computerMove

        #Else Propagate Player move, make the optimal move for the player in the particle
        self.board.turn = config.PLAYER_COLOR
        legalMoves = list(self.board.generate_legal_moves())
        if legalMoves:
            randomMove = random.choice(legalMoves)
            self.board.push(randomMove)
            return randomMove
        
        return