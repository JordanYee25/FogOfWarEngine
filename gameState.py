
import config
import chess
import sunfish
import time

#File for running game operations. This will handle things like the board state and interacting with the chessAPI
class gameState:

    #board is a state of the board currently
    #move is the last move that resulted in this new board
    #boardState has a param for board as it doesnt assume all board begin from the zero move state
    #This allows any variation of chess board to be input
    def __init__(self, board : chess.Board = chess.Board()):
        self.board = board.copy() 
        self.turn = self.board.turn

        #Bad code, needs to be child of board
        self.winner = None # 'white' or 'black'
        self.draw = False

        # Integer value of points, white_pts being a value of 5 (for example) means that 
        # white has captured exactly enough of blacks pieces to get 5 points
        # Pawn = 1      Knight = 3
        # Bishop = 3    Rook = 5
        # Queen = 9     King = Win condt
        # self.white_pts = 0 
        # self.black_pts = 0  

    # Ret True or False (game not over)
    def isGameOver(self):
        return self.board.is_game_over()
    
    #Convert a pygame board to sunfish board, see sunfish.py for more details
    #A sunfish board is represented as a 120 character string where each character is either a space or a piece (rnbqkp)
    #The board dimensions are 10 wide by 12 tall, the width has a padding of 1 and the length/files have a padding of 2
    #To get the back rank of black for example, it would be the characters of indexes 20-29, where 20 is the padded square and 21 is the queenside rook A8
    #                #   0 -  9
    # "          "  #  10 - 19
    # " rnbqkbnr "  #  20 - 29
    # " pppppppp "  #  30 - 39
    # " ........ "  #  40 - 49
    # " ........ "  #  50 - 59
    # " ........ "  #  60 - 69
    # " ........ "  #  70 - 79
    # " PPPPPPPP "  #  80 - 89
    # " RNBQKBNR "  #  90 - 99
    # "          "  # 100 -109
    # "          "  # 110 -119
    def game2Sunfish(self):
        sunfishBoard = [" "]*120

        #Set empty board with periods as squares
        for row in range(12):
            sunfishBoard[(row + 1) * 10 - 1] = "\n"
        for rank in range(8):
            for file in range(8):
                index = (7 - rank + 2) * 10 + (file + 1)
                sunfishBoard[index] = "."


        for square in chess.SQUARES:
            piece = self.board.piece_at(square)
            if piece:
                file = chess.square_file(square)
                rank = chess.square_rank(square)
                sunfish_index = (7 - rank + 2) * 10 + (file + 1)
                sunfishBoard[sunfish_index] = piece.symbol()
        
        boardString = "".join(sunfishBoard)
        # Sunfish always thinks it is white
        # If black, flip the board and swap piece case so black becomes "white" from Sunfish's view
        if self.board.turn == chess.BLACK:
            boardString = boardString[::-1].swapcase()

        return boardString
    
    def sunfishMove2ChessMove(self, sunfishMove):\
        #Sunfish retuns the move as the from square and dest square as ints, and promotion. My implementation currently only promotes to queen
        fromIndex, destIndex, _ = sunfishMove
        
        if self.board.turn == chess.BLACK:
            fromIndex = 119 - fromIndex
            destIndex = 119 - destIndex

        fromFile = (fromIndex % 10) - 1
        fromRank = 7 - (fromIndex // 10 - 2)
        
        destFile = (destIndex % 10) - 1
        destRank = 7 - (destIndex // 10 - 2)
        
        return chess.Move(chess.square(fromFile, fromRank), chess.square(destFile, destRank))
    
    def getSunfishMove(self):
        boardString = self.game2Sunfish()
        #print(boardString)

        # A sunfish position is represented as a tuple of (board, score, wc, bc, ep, kp) where:
        # board -- a 120 char representation of the board
        # score -- the board evaluation
        # wc -- the castling rights, [west/queen side, east/king side]
        # bc -- the opponent castling rights, [west/king side, east/queen side]
        # ep - the en passant square / allows for en passent 
        # kp - the king passant square / makes sure the king cant be captured through en passent

        # Get from pychess if castling rights are available for each side and en passant square if it exists, otherwise 0
        whiteCastlingRights = (self.board.has_queenside_castling_rights(chess.WHITE), self.board.has_kingside_castling_rights(chess.WHITE))
        blackCastlingRights = (self.board.has_queenside_castling_rights(chess.BLACK), self.board.has_kingside_castling_rights(chess.BLACK))
        
        ep = self.board.ep_square if self.board.ep_square else 0
        kp = 0

        pos = sunfish.Position(boardString, 0, whiteCastlingRights, blackCastlingRights, ep, kp)
        searcher = sunfish.Searcher()
        start = time.time()
        best_move = None
        for depth, gamma, score, move in searcher.search([pos]):
            if move is not None:
                best_move = move

            #Only allow break if sunfish has found a move and it's depth and time are above the thresholds
            if best_move and (depth >= config.SUNFISH_DEPTH or (time.time() - start > config.SUNFISH_TIME)):  # 1.5 second time limit
                break
        #print(best_move)
        return self.sunfishMove2ChessMove(best_move)