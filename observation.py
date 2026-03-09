import chess



# Given either white or black, return a board that only has piece visibility for that color

class Observation:
    def __init__(self, board, color):
        self.fullBoard = board  #only passed into getVisibleSquares and getVisiblePieces 
        self.color = color
        self.visibleSquares =  self.getVisibleSquares()  #Set of all squares visible to the self.color
        self.visiblePieces = self.getVisiblePieces()     #Dict , Where key is square and values is Chess.Piece(chess.PieceType, chess.Color) 

    #Visible squares are chess squares that self.color either has a piece on or can move to with a piece
    def getVisibleSquares(self):
        visibleSquares = set()  #Set cannot have duplicates, even if a square is visible from multiple pieces

        #Add your own pieces/squares
        for square in chess.SQUARES:
            piece = self.fullBoard.piece_at(square)
            if piece and piece.color == self.color:
                visibleSquares.add(square)  # Add the square the piece is on
        
        originalTurn = self.fullBoard.turn
        self.fullBoard.turn = self.color
        
        #Add squares reachable through legal moves for self.color
        for move in self.fullBoard.generate_legal_moves():
            piece = self.fullBoard.piece_at(move.from_square)
            if piece and piece.color == self.color:
                visibleSquares.add(move.to_square)  # Add the square the piece can move to
        
        self.fullBoard.turn = originalTurn
        return visibleSquares

    #Visible pieces returns a dict of chess squares that have a piece of either color on it that is visible to self.color
    #Each dict entry key is the square of the piece, the value is a piece object with piece type and color information
    #Takes visible squares from self.visibleSquares and compares to the fullBoard if there is a piece on that square
    def getVisiblePieces(self):
        visiblePieces = {}

        for square in self.visibleSquares:
            piece = self.fullBoard.piece_at(square) #Accesses full board but only compares using visible squares, so there there is no chance of seeing pieces on invisible squares
            if piece:
                visiblePieces[square] = piece   #if a piece is seen multiple times then it will overwrite

        return visiblePieces
                    
