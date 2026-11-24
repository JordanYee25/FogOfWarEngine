import random
import time
from collections import Counter, namedtuple

import chess

import sunfish
from beliefState import beliefState

# The Fog of War engine. It keeps track of what one side knows (its own pieces exactly, the enemy pieces it can
# see, and a histogram belief of the ones it can't) and suggests moves for that side.
#
# Fog of War rules used here: you see every square one of your pieces could move to, there is no check, and the
# game ends when a king is captured. Sunfish is a king capture engine as well, so it fits these rules.
#
# Move choice: a handful of complete boards are drawn from the belief (the most likely board plus random samples).
# Sunfish picks its favourite move on each one, then every candidate is scored on every board and the scores are
# averaged. A move that is great on one imagined board but loses the king on others will not win the vote.

DEFAULT_THINK_TIME = 3.0
DEFAULT_SAMPLES = 8
MAX_CANDIDATES = 6
SCORE_CLIP = 2500           # Stops one board where a king falls from drowning out every other board
KING_DANGER_PENALTY = 1200  # Centipawns taken off a move per unit of probability that a hidden piece can take our king

Suggestion = namedtuple("Suggestion", "move label score votes kingLoss kingWin samples depth danger")
OpponentReport = namedtuple("OpponentReport", "enemies capturedOwn toSquare fromSquare moverTypes knownMove promotion castleRook description")


#############################
#   Sunfish Conversions
#############################

# A sunfish board is a 120 character string, 10 wide and 12 tall. Each row is a space of padding, the 8 squares
# of a rank, then a newline. Two padding rows sit above and below the board, so A8 is index 21 and A1 is index 91.
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
# Sunfish always thinks it is white (upper case, moving up the board). For black the board is rotated 180
# degrees and the letter cases are swapped, which Position.rotate() does for us.

def square2Sunfish(square):
    return (9 - chess.square_rank(square)) * 10 + chess.square_file(square) + 1


def sunfish2Square(index):
    return chess.square(index % 10 - 1, 9 - index // 10)


def board2Sunfish(board, turn, castling):
    """castling = (whiteQueenside, whiteKingside, blackQueenside, blackKingside)"""
    cells = [" "] * 120
    for row in range(12):
        cells[row * 10 + 9] = "\n"
    for square in chess.SQUARES:
        cells[square2Sunfish(square)] = "."
    score = 0
    for square, piece in board.piece_map().items():
        index = square2Sunfish(square)
        symbol = piece.symbol()
        cells[index] = symbol
        if symbol.isupper():
            score += sunfish.pst[symbol][index]
        else:
            score -= sunfish.pst[symbol.upper()][119 - index]

    whiteQueenside, whiteKingside, blackQueenside, blackKingside = castling
    ep = square2Sunfish(board.ep_square) if board.ep_square is not None else 0
    # wc is [west, east] for the side to move, bc is the opponent's rights seen from the other side of the board
    position = sunfish.Position("".join(cells), score, (whiteQueenside, whiteKingside), (blackKingside, blackQueenside), ep, 0)
    return position if turn == chess.WHITE else position.rotate()


def sunfishMove2Chess(move, turn):
    i, j = move.i, move.j
    if turn == chess.BLACK:
        i, j = 119 - i, 119 - j
    promotion = chess.Piece.from_symbol(move.prom).piece_type if move.prom else None
    return chess.Move(sunfish2Square(i), sunfish2Square(j), promotion)


def chessMove2Sunfish(move, turn):
    i, j = square2Sunfish(move.from_square), square2Sunfish(move.to_square)
    if turn == chess.BLACK:
        i, j = 119 - i, 119 - j
    promotion = chess.piece_symbol(move.promotion).upper() if move.promotion else ""
    return sunfish.Move(i, j, promotion)


# MTD-bi search to a fixed depth, the same way sunfish's own iterative deepening narrows in on a score
def fixedDepthScore(searcher, position, depth):
    lower, upper = -sunfish.MATE_UPPER, sunfish.MATE_UPPER
    gamma = position.score
    while lower < upper - sunfish.EVAL_ROUGHNESS:
        score = searcher.bound(position, gamma, depth, can_null=False)
        if score >= gamma:
            lower = score
        else:
            upper = score
        gamma = (lower + upper + 1) // 2
    return (lower + upper) // 2


def moveLabel(board, move):
    """Short algebraic name for a move (no check marks, there is no check in Fog of War)."""
    piece = board.piece_at(move.from_square)
    if piece is None:
        return move.uci()
    if piece.piece_type == chess.KING and abs(chess.square_file(move.from_square) - chess.square_file(move.to_square)) == 2:
        return "O-O" if chess.square_file(move.to_square) == 6 else "O-O-O"
    target = board.piece_at(move.to_square)
    capture = (target is not None and target.color != piece.color) or board.is_en_passant(move)
    toName = chess.square_name(move.to_square)
    if piece.piece_type == chess.PAWN:
        label = (chess.FILE_NAMES[chess.square_file(move.from_square)] + "x" if capture else "") + toName
        if move.promotion:
            label += "=" + chess.piece_symbol(move.promotion).upper()
        return label
    rivals = [m for m in board.generate_pseudo_legal_moves()
              if m.to_square == move.to_square and m.from_square != move.from_square
              and board.piece_type_at(m.from_square) == piece.piece_type]
    disambiguation = ""
    if rivals:
        if all(chess.square_file(m.from_square) != chess.square_file(move.from_square) for m in rivals):
            disambiguation = chess.FILE_NAMES[chess.square_file(move.from_square)]
        elif all(chess.square_rank(m.from_square) != chess.square_rank(move.from_square) for m in rivals):
            disambiguation = chess.RANK_NAMES[chess.square_rank(move.from_square)]
        else:
            disambiguation = chess.square_name(move.from_square)
    return piece.symbol().upper() + disambiguation + ("x" if capture else "") + toName


#############################
#   Search
#############################

class SearchJob:
    """Everything a search needs, copied out of the engine so it can run on a background thread."""

    def __init__(self, boards, candidates, labels, turn, castling, thinkTime, danger=None):
        self.positions = [board2Sunfish(board, turn, castling) for board in boards]
        self.candidates = list(candidates)
        self.labels = labels
        self.danger = danger or {}      # move -> probability a hidden enemy piece can capture our king afterwards
        self.turn = turn
        self.thinkTime = thinkTime

    def run(self):
        if not self.candidates:
            return []
        if len(self.candidates) == 1:
            move = self.candidates[0]
            return [Suggestion(move, self.labels[move], 0, 0, 0, 0, len(self.positions), 0, self.danger.get(move, 0.0))]

        start = time.time()
        deadline = start + self.thinkTime
        candidateSet = set(self.candidates)

        # 1. Let sunfish propose its best move on each imagined board
        votes = Counter()
        proposeTime = self.thinkTime * 0.4 / len(self.positions)
        for position in self.positions:
            searcher = sunfish.Searcher()
            began = time.time()
            best = None
            for depth, gamma, score, move in searcher.search([position]):
                if move is not None and score >= gamma:
                    chessMove = sunfishMove2Chess(move, self.turn)
                    if chessMove in candidateSet:
                        best = chessMove
                elapsed = time.time() - began
                if (best and elapsed > proposeTime) or elapsed > proposeTime * 3 or depth > 30:
                    break
            if best:
                votes[best] += 1

        # Pad the shortlist with moves sunfish's move ordering likes on the most likely board, and always keep the
        # safest move for our king in the running
        shortlist = [move for move, _ in votes.most_common(MAX_CANDIDATES)]
        if self.danger:
            safest = min(self.candidates, key=lambda m: (self.danger.get(m, 0.0), -self.positions[0].value(chessMove2Sunfish(m, self.turn))))
            if safest not in shortlist and self.danger.get(shortlist[0] if shortlist else safest, 0.0) > 0.05:
                shortlist.append(safest)
        mapPosition = self.positions[0]
        ordered = sorted(self.candidates, key=lambda m: -mapPosition.value(chessMove2Sunfish(m, self.turn)))
        for move in ordered:
            if len(shortlist) >= max(3, len(votes)) or len(shortlist) >= MAX_CANDIDATES:
                break
            if move not in shortlist:
                shortlist.append(move)

        # 2. Score every shortlisted move on every board, deepening while there is time left
        searchers = []
        for _ in self.positions:
            searcher = sunfish.Searcher()
            searcher.history = set()
            searchers.append(searcher)
        results, completedDepth = {}, 0
        for depth in range(1, 10):
            current = {}
            finished = True
            for move in shortlist:
                sunfishMove = chessMove2Sunfish(move, self.turn)
                scores = []
                for searcher, position in zip(searchers, self.positions):
                    # Depth 1 always finishes: it is cheap and catches hanging pieces and kings
                    if depth > 1 and time.time() > deadline:
                        finished = False
                        break
                    scores.append(-fixedDepthScore(searcher, position.move(sunfishMove), depth - 1))
                if not finished:
                    break
                current[move] = scores
            if not finished:
                break
            results, completedDepth = current, depth

        suggestions = []
        for move, scores in results.items():
            clipped = [max(-SCORE_CLIP, min(SCORE_CLIP, s)) for s in scores]
            danger = self.danger.get(move, 0.0)
            suggestions.append(Suggestion(
                move=move,
                label=self.labels[move],
                score=sum(clipped) / len(clipped) - KING_DANGER_PENALTY * danger,
                votes=votes[move],
                kingLoss=sum(1 for s in scores if s <= -sunfish.MATE_LOWER),
                kingWin=sum(1 for s in scores if s >= sunfish.MATE_LOWER),
                samples=len(scores),
                depth=completedDepth,
                danger=danger,
            ))
        suggestions.sort(key=lambda s: (-s.score, -s.votes))
        return suggestions


#############################
#   Engine
#############################

class FogEngine:
    def __init__(self, color, thinkTime=DEFAULT_THINK_TIME, numSamples=DEFAULT_SAMPLES, seed=None):
        self.color = color
        self.enemyColor = not color
        self.thinkTime = thinkTime
        self.numSamples = numSamples
        self.rng = random.Random(seed)

        self.belief = beliefState(color)

        # What we know for sure: our own pieces, plus the enemy pieces we can currently see
        self.board = chess.Board()
        for square, piece in list(self.board.piece_map().items()):
            if piece.color == self.enemyColor:
                self.board.remove_piece_at(square)
        self.board.turn = color

        self.toMove = chess.WHITE
        self.blocked = set()            # Squares in front of our pawns that are fogged because something blocks them
        self.lastDoublePush = None      # Our pawn that just moved two squares (it can be captured en passant)
        self.moveLog = []
        self.result = None              # "win" or "loss" once a king is captured

    @property
    def ourTurn(self):
        return self.toMove == self.color

    #############################
    #   What we know
    #############################

    def ownSquares(self, board=None):
        board = board or self.board
        return {square for square, piece in board.piece_map().items() if piece.color == self.color}

    def reportedEnemies(self):
        return {square: piece.piece_type for square, piece in self.board.piece_map().items() if piece.color == self.enemyColor}

    def _boardWith(self, enemies=None, capturedOwn=(), blocked=None):
        board = self.board.copy(stack=False)
        for square in capturedOwn:
            board.remove_piece_at(square)
        if enemies is not None:
            for square, piece in list(board.piece_map().items()):
                if piece.color == self.enemyColor:
                    board.remove_piece_at(square)
            for square, pieceType in enemies.items():
                board.set_piece_at(square, chess.Piece(pieceType, self.enemyColor))
        # A fogged square in front of our pawn has something on it. A stand in pawn stops our pawn moving there.
        for square in (self.blocked if blocked is None else blocked):
            if board.piece_at(square) is None:
                board.set_piece_at(square, chess.Piece(chess.PAWN, self.enemyColor))
        board.turn = self.color
        return board

    # Squares we can see: our own pieces and every square they could move to
    def visibleSquares(self, enemies=None, capturedOwn=(), blocked=None):
        blocked = self.blocked if blocked is None else blocked
        board = self._boardWith(enemies, capturedOwn, blocked)
        visible = self.ownSquares(board)
        for move in board.generate_pseudo_legal_moves():
            visible.add(move.to_square)
        return visible - set(blocked)

    # Squares our pawns could push to (one or two steps). Only these can be fogged-but-occupied ("blocked"):
    # anything else an unseen piece stands on would be visible as a capture.
    def pawnPushSquares(self):
        step = 8 if self.color == chess.WHITE else -8
        startRank = 1 if self.color == chess.WHITE else 6
        squares = set()
        for square, piece in self.board.piece_map().items():
            if piece.color == self.color and piece.piece_type == chess.PAWN and 0 <= square + step < 64:
                squares.add(square + step)
                if chess.square_rank(square) == startRank and self.board.piece_at(square + step) is None:
                    squares.add(square + 2 * step)
        return squares

    # Squares our pawns could capture on. These are only visible while an enemy piece stands on them.
    def pawnCaptureSquares(self):
        squares = set()
        for square, piece in self.board.piece_map().items():
            if piece.color == self.color and piece.piece_type == chess.PAWN:
                squares |= set(chess.SquareSet(chess.BB_PAWN_ATTACKS[self.color][square]))
        return squares

    def candidateMoves(self):
        board = self._boardWith()
        return [move for move in board.generate_pseudo_legal_moves() if move.to_square not in self.blocked]

    def ourCastling(self):
        board = self.board
        rights = {}
        for color in (chess.WHITE, chess.BLACK):
            rights[color] = (board.has_queenside_castling_rights(color), board.has_kingside_castling_rights(color))
        return rights

    #############################
    #   Thinking
    #############################

    def prepareSearch(self, thinkTime=None, restrictTo=None):
        candidates = self.candidateMoves()
        if restrictTo is not None:
            restrictTo = set(restrictTo)
            candidates = [move for move in candidates if move in restrictTo] or list(restrictTo)
        board = self._boardWith()
        labels = {move: moveLabel(board, move) for move in candidates}

        boards = [self.belief.mostLikelyBoard(self.board)]
        for _ in range(self.numSamples - 1):
            boards.append(self.belief.sampleBoard(self.board, "sample", self.rng))
        for sampled in boards:
            sampled.ep_square = self.board.ep_square

        # Our castling rights are known. The enemy's are guessed from whether king and rook sit at home.
        ours = self.ourCastling()[self.color]
        homeRank = 7 if self.enemyColor == chess.BLACK else 0
        mapBoard = boards[0]
        enemyKingHome = mapBoard.piece_at(chess.square(4, homeRank)) == chess.Piece(chess.KING, self.enemyColor)
        rook = chess.Piece(chess.ROOK, self.enemyColor)
        theirs = (enemyKingHome and mapBoard.piece_at(chess.square(0, homeRank)) == rook,
                  enemyKingHome and mapBoard.piece_at(chess.square(7, homeRank)) == rook)
        white, black = (ours, theirs) if self.color == chess.WHITE else (theirs, ours)
        castling = (white[0], white[1], black[0], black[1])

        danger = {move: self.kingDanger(move) for move in candidates}
        return SearchJob(boards, candidates, labels, self.color, castling, thinkTime or self.thinkTime, danger)

    # Probability that, after we play `move`, some enemy piece (seen or hidden) could capture our king
    def kingDanger(self, move):
        board = self._boardWith()
        captured = move.to_square if board.color_at(move.to_square) == self.enemyColor else None
        board.push(move)
        king = board.king(self.color)
        if king is None:
            return 1.0
        own = self.ownSquares(board)
        blockers = {s for s, p in board.piece_map().items() if p.color == self.enemyColor}
        return self.belief.attackProbability(king, own, blockers, ignore=captured)

    def suggest(self, thinkTime=None, restrictTo=None):
        return self.prepareSearch(thinkTime, restrictTo).run()

    #############################
    #   Our move
    #############################

    def applyOurMove(self, move):
        board = self._boardWith(blocked=())
        label = moveLabel(board, move)
        piece = board.piece_at(move.from_square)

        capturedSquare = None
        if board.is_en_passant(move):
            capturedSquare = move.to_square + (-8 if self.color == chess.WHITE else 8)
        elif board.piece_at(move.to_square) is not None and board.color_at(move.to_square) == self.enemyColor:
            capturedSquare = move.to_square
        if capturedSquare is not None:
            capturedType = board.piece_type_at(capturedSquare) or chess.PAWN
            self.belief.removePieceAt(capturedSquare, capturedType)
            if capturedType == chess.KING:
                self.result = "win"

        self.board.turn = self.color
        self.board.push(move)
        self.board = self.board.copy(stack=False)
        self.board.ep_square = None

        squares = [move.to_square]
        if piece and piece.piece_type == chess.KING and abs(move.to_square - move.from_square) == 2:
            homeRank = chess.square_rank(move.from_square)
            squares.append(chess.square(5 if chess.square_file(move.to_square) == 6 else 3, homeRank))
        self.belief.markOccupiedByUs(squares)

        isDoublePush = piece and piece.piece_type == chess.PAWN and abs(move.to_square - move.from_square) == 16
        self.lastDoublePush = move.to_square if isDoublePush else None
        self.blocked = {s for s in self.blocked if s in self.pawnPushSquares() and self.board.piece_at(s) is None}
        self.toMove = self.enemyColor
        self.moveLog.append(label)
        return label

    # Record enemy pieces seen without the enemy having moved (e.g. what our last move uncovered)
    def applySightings(self, enemies, blocked=None, visibleOverride=None):
        if blocked is not None:
            self.blocked = set(blocked)
        visible = set(visibleOverride) if visibleOverride is not None else self.visibleSquares(enemies)
        enemies = {s: t for s, t in enemies.items() if s in visible}
        self._setEnemies(enemies)
        self.belief.observationStep(visible, enemies, self.ownSquares())

    def _setEnemies(self, enemies):
        for square, piece in list(self.board.piece_map().items()):
            if piece.color == self.enemyColor:
                self.board.remove_piece_at(square)
        for square, pieceType in enemies.items():
            self.board.set_piece_at(square, chess.Piece(pieceType, self.enemyColor))

    #############################
    #   Their move
    #############################

    def _reachable(self, pieceType, fromSquare, toSquare, capture=False):
        """Could an enemy piece of this type move fromSquare -> toSquare on the board as we know it?"""
        own = self.ownSquares()
        blockers = set(self.reportedEnemies()) - {fromSquare}
        target = toSquare if capture else None
        return toSquare in self.belief._destinations(pieceType, fromSquare, own, blockers, target)

    def interpretOpponentMove(self, enemies, capturedOwn=(), blocked=None, visibleOverride=None):
        """Work out what the enemy's move must have been from what is visible now compared to before.
        Nothing changed means the move was hidden in the fog. Returns an OpponentReport."""
        capturedOwn = [s for s in capturedOwn if self.board.color_at(s) == self.color]
        blocked = self.blocked if blocked is None else set(blocked)
        if visibleOverride is not None:
            visibleAfter = set(visibleOverride)
        else:
            visibleAfter = self.visibleSquares(enemies, capturedOwn, blocked)
        enemies = {s: t for s, t in enemies.items() if s in visibleAfter}
        visibleBefore = self.visibleSquares()
        before = self.reportedEnemies()

        removed = {s: t for s, t in before.items() if enemies.get(s) != t}
        added = {s: t for s, t in enemies.items() if before.get(s) != t}

        toSquare = fromSquare = moverTypes = knownMove = promotion = castleRook = None
        name = lambda s: chess.square_name(s)
        pieceName = lambda t: chess.piece_name(t)
        description = []

        if capturedOwn:
            target = capturedOwn[0]
            capturedPiece = self.board.piece_at(target)
            description.append(f"Your {pieceName(capturedPiece.piece_type)} on {name(target)} was captured")
            toSquare = target
            epSquare = None
            if capturedPiece.piece_type == chess.PAWN and target == self.lastDoublePush:
                epSquare = target + (-8 if self.color == chess.WHITE else 8)
            if target in enemies:
                moverTypes = {enemies[target]}
            elif epSquare is not None and enemies.get(epSquare) == chess.PAWN:
                toSquare, moverTypes = epSquare, {chess.PAWN}
                description[-1] += " en passant"
            if moverTypes:
                description[-1] += f" by a {pieceName(next(iter(moverTypes)))}"
            sources = [s for s, t in removed.items() if (not moverTypes or t in moverTypes)
                       and self._reachable(t, s, toSquare, capture=True)]
            if len(sources) == 1:
                fromSquare = sources[0]
                moverTypes = {removed[fromSquare]}
                description[-1] += f" from {name(fromSquare)}"
            if toSquare not in enemies and toSquare in visibleAfter:
                description.append(f"Tip: you can still see {name(toSquare)}, so place the piece that took yours there")
        else:
            # Castling: king and rook both jump
            kingFrom = [s for s, t in removed.items() if t == chess.KING]
            kingTo = [s for s, t in added.items() if t == chess.KING]
            if kingFrom and kingTo and abs(kingFrom[0] - kingTo[0]) == 2 and chess.square_rank(kingFrom[0]) == chess.square_rank(kingTo[0]):
                rank = chess.square_rank(kingFrom[0])
                kingside = chess.square_file(kingTo[0]) == 6
                knownMove = (kingFrom[0], kingTo[0])
                castleRook = (chess.square(7 if kingside else 0, rank), chess.square(5 if kingside else 3, rank))
                description.append("Opponent castled " + ("kingside" if kingside else "queenside"))
            elif len(added) == 1 and len(removed) <= 1:
                square, pieceType = next(iter(added.items()))
                # Could the piece have just arrived? Yes if we could see the square before (it was empty). Also yes
                # if nothing disappeared: a square only a pawn capture sees is visible just while a piece is on it,
                # and if nothing moved out of the way of our rays the piece can't have been revealed any other way.
                arrived = square in visibleBefore or not removed or square in self.pawnCaptureSquares()
                if removed:
                    origin, originType = next(iter(removed.items()))
                    lastRank = 0 if self.enemyColor == chess.BLACK else 7
                    if originType == chess.PAWN and pieceType != chess.PAWN and chess.square_rank(square) == lastRank \
                            and (self._reachable(chess.PAWN, origin, square)):
                        knownMove, promotion = (origin, square), pieceType
                        description.append(f"Opponent promoted {name(origin)}-{name(square)}={chess.piece_symbol(pieceType).upper()}")
                    elif originType == pieceType and arrived and self._reachable(pieceType, origin, square):
                        knownMove = (origin, square)
                        description.append(f"Opponent moved {pieceName(pieceType)} {name(origin)}-{name(square)}")
                if knownMove is None and arrived and pieceType == chess.PAWN:
                    # A pawn appearing on its fourth rank most likely made a double push. That matters because
                    # it can then be captured en passant.
                    step = 8 if self.enemyColor == chess.WHITE else -8
                    doubleRank = 3 if self.enemyColor == chess.WHITE else 4
                    if chess.square_rank(square) == doubleRank:
                        passed, origin = square - step, square - 2 * step
                        pawnGrid = self.belief.typeDistribution(chess.PAWN)
                        fromPassed = 0.0 if passed in visibleBefore else pawnGrid[passed]
                        if self.board.piece_at(passed) is None and pawnGrid[origin] > fromPassed:
                            knownMove = (origin, square)
                            description.append(f"Opponent pushed a pawn {name(origin)}-{name(square)}")
                if knownMove is None and arrived:
                    toSquare, moverTypes = square, {pieceType}
                    if chess.square_rank(square) == (0 if self.enemyColor == chess.BLACK else 7) and pieceType != chess.PAWN:
                        moverTypes.add(chess.PAWN)
                    description.append(f"A {pieceName(pieceType)} came out of the fog to {name(square)}")
                elif knownMove is None:
                    description.append(f"New sighting: {pieceName(pieceType)} on {name(square)}")
            elif len(removed) == 1 and not added:
                origin, originType = next(iter(removed.items()))
                fromSquare, moverTypes = origin, {originType}
                description.append(f"The {pieceName(originType)} on {name(origin)} moved into the fog")
            elif not added and not removed:
                description.append("Nothing visible changed: the move was hidden in the fog")
            else:
                description.append(f"{len(added)} piece(s) appeared and {len(removed)} disappeared")

        if knownMove:
            fromSquare, toSquare = knownMove
            moverTypes = {chess.PAWN} if promotion else {before.get(fromSquare) or enemies[toSquare]}

        return OpponentReport(enemies, capturedOwn, toSquare, fromSquare, moverTypes, knownMove,
                              promotion, castleRook, description)

    def applyOpponentMove(self, enemies, capturedOwn=(), blocked=None, visibleOverride=None):
        """The enemy has moved. enemies is every enemy piece visible now ({square: pieceType}), capturedOwn
        the squares of any of our pieces that were just taken. Leave both unchanged for a hidden move."""
        if blocked is not None:
            self.blocked = set(blocked)
        report = self.interpretOpponentMove(enemies, capturedOwn, self.blocked, visibleOverride)

        # Prediction step, using the board as it was before the move for what blocked the enemy
        ownBefore = self.ownSquares()
        self.belief.predictionStep(ownBefore, report.toSquare, report.fromSquare, report.moverTypes, self.board.king(self.color))
        if report.promotion:
            self.belief.promoteAt(report.toSquare, report.promotion)
        if report.castleRook:
            self.belief.forceMove(report.castleRook[0], report.castleRook[1], chess.ROOK)

        for square in report.capturedOwn:
            if self.board.piece_type_at(square) == chess.KING:
                self.result = "loss"
            self.board.remove_piece_at(square)
        self._setEnemies(report.enemies)

        # A pawn we saw move two squares can be captured en passant on our turn
        self.board.ep_square = None
        if report.knownMove and report.moverTypes == {chess.PAWN} and not report.promotion:
            origin, destination = report.knownMove
            if abs(destination - origin) == 16:
                self.board.ep_square = (origin + destination) // 2
        self.board.turn = self.color
        self.blocked = {s for s in self.blocked if s in self.pawnPushSquares() and self.board.piece_at(s) is None}

        # Observation step
        visible = set(visibleOverride) if visibleOverride is not None else self.visibleSquares()
        self.belief.observationStep(visible, report.enemies, self.ownSquares())

        self.lastDoublePush = None
        self.toMove = self.color
        self.moveLog.append(self._shortOpponentLabel(report))
        return report

    # Compact notation for the move log: "?" hidden, "Nb8-c6" seen, "B?-b4" arrived from the fog, "Q?xd5" capture
    @staticmethod
    def _shortOpponentLabel(report):
        if report.castleRook:
            return "O-O" if chess.square_file(report.toSquare) == 6 else "O-O-O"
        if report.toSquare is None and report.fromSquare is None:
            return "?"
        pieceType = next(iter(report.moverTypes)) if report.moverTypes and len(report.moverTypes) == 1 else None
        letter = chess.piece_symbol(pieceType).upper() if pieceType else "?"
        origin = chess.square_name(report.fromSquare) if report.fromSquare is not None else "?"
        joiner = "x" if report.capturedOwn else "-"
        destination = chess.square_name(report.toSquare) if report.toSquare is not None else "?"
        label = letter + origin + joiner + destination
        if report.promotion:
            label += "=" + chess.piece_symbol(report.promotion).upper()
        return label
