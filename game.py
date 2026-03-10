import time

import pygame, sys, random, chess, platform
from gameState import gameState
from pygame.locals import *
import config 


class game:

    def __init__(self):
    
        self.gameState = gameState()

        pygame.init()
        self.DISPLAYSURF = pygame.display.set_mode((config.BOARDSIZE, config.BOARDSIZE), 0, 32)
        pygame.display.set_caption('Chess!')
            
        self.fps = pygame.time.Clock()

        self.selectedPiece = None
        self.selectedPieceSquare = None
        self.SQUARESIZE = config.BOARDSIZE / 8 
        self.PGN = []
        
        self.UNICODE_PIECES = {
            "K": "♔",
            "Q": "♕",
            "R": "♖",
            "B": "♗",
            "N": "♘",
            "P": "♙",
            "k": "♚",
            "q": "♛",
            "r": "♜",
            "b": "♝",
            "n": "♞",
            "p": "♟",
        }

        # Gets the font per system, optherwise pieces appear as empty rectangle
        self.PIECE_FONT = pygame.font.SysFont('arial', int(self.SQUARESIZE * 0.8))
        if platform.system() == "Windows":
            self.PIECE_FONT = pygame.font.SysFont('segoeuisymbol', int(self.SQUARESIZE * 0.8))  # Windows
        elif platform.system() == "Darwin": 
            self.PIECE_FONT = pygame.font.SysFont('applesymbols', int(self.SQUARESIZE * 0.8))  # Mac

        self.redraw()

    #*****************************
    #       Diplay Functions
    #*****************************

    #Gameboard is created by two for loop that alternate color of square for all 64 squares
    #If row and column is odd, set as dark square
    def drawBoard(self, Display):
        for row in range(8):
            for col in range(8):
                if (row + col) % 2 == 1:  #dark squares
                    rect = pygame.Rect(col * self.SQUARESIZE,row * self.SQUARESIZE, self.SQUARESIZE, self.SQUARESIZE)
                    pygame.draw.rect(Display, config.SQUARECOLOR_DARK, rect)
                else:
                    rect = pygame.Rect(col * self.SQUARESIZE,row * self.SQUARESIZE, self.SQUARESIZE, self.SQUARESIZE)
                    pygame.draw.rect(Display, config.SQUARECOLOR_LIGHT, rect)


    def drawPieces(self, Display):
        # Iterate through the visible squares from observation
        # Draw pieces depending on whether player is white or black, and what piece it is
        
        observation = self.gameState.getObservation(config.PLAYER_COLOR)

        for visiblePiece in observation.visiblePieces:
            piece = observation.visiblePieces[visiblePiece].symbol()  # Returns 'K', 'q', 'P', etc.
            col , row = self.square2Display(visiblePiece)

            unicodePiece = self.UNICODE_PIECES[piece]
            pieceSurface = self.PIECE_FONT.render(unicodePiece, True, (0, 0, 0))
            #Center
            pieceRect = pieceSurface.get_rect()
            pieceRect.center = (col * self.SQUARESIZE + self.SQUARESIZE / 2, row * self.SQUARESIZE + self.SQUARESIZE / 2)
            Display.blit(pieceSurface, pieceRect)

        self.drawFog(Display, observation.visibleSquares)
            
        #debug to show visible squares, shows app pieces regardless of side
        # for square in chess.SQUARES:
        #     piece = self.gameState.board.piece_at(square)
        #     if piece:
        #         col, row = self.square2Display(square)
        
        #         piece_symbol = piece.symbol()  # Returns 'K', 'q', 'P', etc.
        #         unicode_piece = self.UNICODE_PIECES[piece_symbol]
        #         piece_surface = self.PIECE_FONT.render(unicode_piece, True, (0, 0, 0))
        #         #Center
        #         piece_rect = piece_surface.get_rect()
        #         piece_rect.center = (col * self.SQUARESIZE + self.SQUARESIZE /
        #                             2, row * self.SQUARESIZE + self.SQUARESIZE / 2)
        #         Display.blit(piece_surface, piece_rect)
        # #only draw fog if it is the players turn
        # if self.gameState.turn == config.PLAYER_COLOR:
        #     self.drawFog(Display, observation.visibleSquares)

    #Given a square, if there exists a piece return the squares that it can move to
    def drawMoves(self, square):
        legalPieceMoves = []
        for move in self.legalPieceMoves(square):
            legalPieceMoves.append(move.to_square)

        self.drawMoveIndicators(self.DISPLAYSURF, legalPieceMoves)

    #Whenver the user clicks on a piece circles should pop up that show where the piece can move
    def drawMoveIndicators(self, Display, moveSquare):
        #Clear dots by redrawing the game board and pieces from the pychess board
        self.redraw()

        for square in moveSquare:
            col, row = self.square2Display(square)

            center_x = int(col * self.SQUARESIZE + self.SQUARESIZE // 2)
            center_y = int(row * self.SQUARESIZE + self.SQUARESIZE // 2)
            radius = int(self.SQUARESIZE // 6)
            
            #Change to semi transparent circle
            surface = pygame.Surface((self.SQUARESIZE, self.SQUARESIZE), pygame.SRCALPHA)
            pygame.draw.circle(surface, (50, 50, 50, 150), (radius, radius), radius)
            Display.blit(surface, (center_x - radius, center_y - radius))

    def drawFog(self, Display, visibleSquares):
        for square in chess.SQUARES:
            if square not in visibleSquares:
                col, row = self.square2Display(square)
                rect = pygame.Rect(col * self.SQUARESIZE, row * self.SQUARESIZE, self.SQUARESIZE, self.SQUARESIZE)
                pygame.draw.rect(Display, (100, 100, 100), rect)

    def legalPieceMoves(self, square):
        piece = self.gameState.board.piece_at(square)
        if not piece: return []
        
        legalMoves = self.gameState.board.legal_moves
        legalPieceMoves = []

        for move in legalMoves:
            if move.from_square == square:
                legalPieceMoves.append(move)
    
        return legalPieceMoves

    def display2Square(self, x, y):
        col = int(x / self.SQUARESIZE)
        rank = int(y / self.SQUARESIZE)
        file = col if config.PLAYER_COLOR == chess.WHITE else 7 - col
        rank = 7 - rank if config.PLAYER_COLOR == chess.WHITE else rank
        return chess.square(file, rank)

    def square2Display(self, square):
        col = chess.square_file(square)
        rank = chess.square_rank(square)
        row = 7 - rank if config.PLAYER_COLOR == chess.WHITE else rank
        col = col if config.PLAYER_COLOR == chess.WHITE else 7 - col
        return col, row

    def redraw(self):
        self.drawBoard(self.DISPLAYSURF)
        self.drawPieces(self.DISPLAYSURF)
        pygame.display.update()



    #*****************************
    #     Logic Game Functions
    #*****************************

    def makeMove(self, clickedSquare): 

        selectedPieceMoves = self.legalPieceMoves(self.selectedPieceSquare)
        for move in selectedPieceMoves:
            if move.to_square == clickedSquare:
                
                selectedMove = move

                if move.promotion:
                    selectedMove = chess.Move(self.selectedPieceSquare, clickedSquare, chess.QUEEN)
                
                self.gameState.board.push(selectedMove)
                self.PGN.append(self.gameState.board.peek().uci()) #Append move to PGN list

                self.redraw()

                return "move"
    
    #Dependent on computerMove being called at the right time, i.e after player has made move
    #Computer will use sunfish to make move, using getSunfishMove() function in gameState and using observation
    def computerMove(self):
        legalMoves = list(self.gameState.board.legal_moves)
        if legalMoves:
            self.redraw()

            self.gameState.propagatePlayerMove()
            self.gameState.updateBeliefState()
            move = self.gameState.getSunfishMove()
            self.gameState.board.push(move)
            self.gameState.propagateComputerMove(move)

            self.PGN.append(self.gameState.board.peek().uci()) #Append move to PGN list
            self.redraw()

            return "move"
        return None
        
    def step(self):
        for event in pygame.event.get():
            if event.type == QUIT:
                pygame.quit()
                sys.exit()   

            if self.gameState.board.turn == config.PLAYER_COLOR:
                if event.type == pygame.MOUSEBUTTONUP: 
                    x, y = event.pos
                    #Convert Display X Y to board X Y square
                    clickedSquare = self.display2Square(x, y)
                    
                    #Check if clicked square has a piece of current player, if so draw moves
                    clickedPiece = self.gameState.board.piece_at(clickedSquare)
                    if clickedPiece and clickedPiece.color == self.gameState.board.turn:
                        self.selectedPiece = clickedPiece
                        self.selectedPieceSquare = clickedSquare
                        self.drawMoves(clickedSquare)   #Draw indication circles
                    
                    return self.makeMove(clickedSquare)
                
        if self.gameState.board.turn != config.PLAYER_COLOR:
            time.sleep(2)
            return self.computerMove()
        

        if self.gameState.isGameOver():
            pygame.display.update()     #possibly add in function to show full board when over
            self.PGN.append(self.gameState.board.result()) #Append result to PGN list
            return "gameover"

        pygame.display.update()
        self.fps.tick(config.FPS)


