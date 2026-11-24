
import random
import chess

# Belief state for Fog of War chess, built as a Histogram (discrete Bayes) filter.
#
# Every enemy piece is tracked on its own 64 square grid: dist[square] is the probability that the piece is on
# that square (0 = A1, 63 = H8). The grids are updated in two steps, once per enemy move:
#
#   Prediction step  - the enemy made a move we may not have seen. Each piece's probability flows along the
#                      squares it could legally move to, weighted by how likely that piece was the one that moved.
#   Observation step - we look at the board. A square we can see with no enemy piece on it has probability 0
#                      for every piece. A square we can see with an enemy piece on it is certain (probability 1)
#                      for the one tracked piece that best explains it. Observations are always true, so
#                      P(observation | state) is either 1 or 0, and all that is left is to renormalise.
#
# Tracking each piece separately (instead of one grid per piece type) keeps information like "this pawn is on the
# e-file" and "this bishop lives on dark squares", which one shared grid per type would blur together.
# typeDistribution() still gives the per type view by summing the grids.

CERTAIN = 0.999     # A piece whose most likely square is at least this probable is treated as known

# Every legal enemy move is assumed equally likely, then nudged by piece type. A move by a king is less
# common than a move by a knight, so a hidden move is less likely to have been a king move.
MOVER_TYPE_WEIGHT = {
    chess.PAWN: 1.0,
    chess.KNIGHT: 1.1,
    chess.BISHOP: 1.0,
    chess.ROOK: 0.8,
    chess.QUEEN: 0.9,
    chess.KING: 0.5,
}

# Players don't move at random: a move that lands on a square attacking our pieces (a threat, a pin, an attack on
# the king) is more likely than a quiet one. Each destination's weight is 1 + these bonuses.
THREAT_BONUS = 0.5          # Per one of our pieces the destination attacks
KING_THREAT_BONUS = 3.0     # If the destination attacks our king

SLIDER_DIRECTIONS = {
    chess.BISHOP: ((1, 1), (1, -1), (-1, 1), (-1, -1)),
    chess.ROOK: ((1, 0), (-1, 0), (0, 1), (0, -1)),
    chess.QUEEN: ((1, 1), (1, -1), (-1, 1), (-1, -1), (1, 0), (-1, 0), (0, 1), (0, -1)),
}


def isLightSquare(square):
    return bool(chess.BB_LIGHT_SQUARES & chess.BB_SQUARES[square])


class TrackedPiece:
    """One enemy piece and the probability grid of where it could be."""

    def __init__(self, pieceType, square=None, squareColor=None):
        self.pieceType = pieceType
        self.dist = [0.0] * 64
        if square is not None:
            self.dist[square] = 1.0
        self.alive = True
        self.squareColor = squareColor  # Bishops only: True for the light squared bishop. None means any colour

    def certainty(self):
        return max(self.dist)

    def mostLikelySquare(self):
        return max(range(64), key=self.dist.__getitem__)

    def __repr__(self):
        square = self.mostLikelySquare()
        return f"{chess.piece_name(self.pieceType)}@{chess.square_name(square)}({self.dist[square]:.2f})"


class beliefState:
    def __init__(self, color=None):
        if color is None:
            import config
            color = not config.PLAYER_COLOR
        self.color = color              # The side this belief state plays for
        self.enemyColor = not color     # The side whose pieces are hidden in the fog

        self.pieces = []                # TrackedPiece for every enemy piece, dead ones included
        self.capturedPieces = {pieceType: 0 for pieceType in chess.PIECE_TYPES}

        self.generateDistributions()

    #############################
    #   Setup and queries
    #############################

    # Every game starts from the same position, so the belief starts out certain
    def generateDistributions(self):
        self.pieces = []
        self.capturedPieces = {pieceType: 0 for pieceType in chess.PIECE_TYPES}
        for square, piece in chess.Board().piece_map().items():
            if piece.color == self.enemyColor:
                squareColor = isLightSquare(square) if piece.piece_type == chess.BISHOP else None
                self.pieces.append(TrackedPiece(piece.piece_type, square, squareColor))

    def alivePieces(self):
        return [piece for piece in self.pieces if piece.alive]

    # Probability that each square holds some enemy piece
    def occupancy(self):
        occupied = [0.0] * 64
        for piece in self.alivePieces():
            for square, probability in enumerate(piece.dist):
                occupied[square] += probability
        return [min(1.0, probability) for probability in occupied]

    # Expected number of enemy pieces of one type on each square (the per type grid view)
    def typeDistribution(self, pieceType):
        grid = [0.0] * 64
        for piece in self.alivePieces():
            if piece.pieceType == pieceType:
                for square, probability in enumerate(piece.dist):
                    grid[square] += probability
        return grid

    # {pieceType: probability} of what enemy piece is on a square
    def squareBreakdown(self, square):
        breakdown = {}
        for piece in self.alivePieces():
            if piece.dist[square] > 0:
                breakdown[piece.pieceType] = breakdown.get(piece.pieceType, 0.0) + piece.dist[square]
        return breakdown

    # Probability that at least one enemy piece attacks `square`, given our pieces on `own` and enemy pieces
    # we can see on `blockers`. `ignore` is a square whose enemy piece is about to be captured.
    def attackProbability(self, square, own, blockers=(), ignore=None):
        # Work backwards from the target: the squares a piece type attacks it from are the squares it reaches
        # moving that way from the target (stopping at, and including, the first piece in the way)
        occupied = (set(own) | set(blockers)) - {square}
        sources = {}
        for pieceType in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN, chess.KING):
            sources[pieceType] = set(self._destinations(pieceType, square, occupied, set(), captureAll=True)) - set(own)
        step = 8 if self.enemyColor == chess.WHITE else -8
        sources[chess.PAWN] = set()
        for fileStep in (-1, 1):
            file = chess.square_file(square) + fileStep
            if 0 <= file <= 7 and 0 <= square - step < 64:
                sources[chess.PAWN].add(chess.square(file, chess.square_rank(square - step)))

        safe = 1.0
        for piece in self.alivePieces():
            if ignore is not None and piece.dist[ignore] >= 0.5:
                continue
            attack = sum(piece.dist[s] for s in sources[piece.pieceType])
            safe *= 1.0 - min(1.0, attack)
        return 1.0 - safe

    def knownPieceCount(self):
        return sum(1 for piece in self.alivePieces() if piece.certainty() >= CERTAIN)

    #############################
    #   Movement model
    #############################

    def _promotionRank(self):
        return 0 if self.enemyColor == chess.BLACK else 7

    # Squares an enemy piece on `square` could move to.
    # own      - squares holding our pieces. The enemy can only land on one if it is the capture `target`
    # blockers - squares that are probably holding another enemy piece
    # target   - the one square the enemy is known to have captured on (or the en passant square)
    # captureAll - include every one of our pieces the enemy piece could capture (used to find what it attacks)
    def _destinations(self, pieceType, square, own, blockers, target=None, captureAll=False):
        destinations = []
        file, rank = chess.square_file(square), chess.square_rank(square)

        if pieceType == chess.PAWN:
            step = 1 if self.enemyColor == chess.WHITE else -1
            startRank = 1 if self.enemyColor == chess.WHITE else 6
            nextRank = rank + step
            if not 0 <= nextRank <= 7:
                return destinations
            oneStep = chess.square(file, nextRank)
            if oneStep not in own and oneStep not in blockers:
                destinations.append(oneStep)
                if rank == startRank:
                    twoStep = chess.square(file, nextRank + step)
                    if twoStep not in own and twoStep not in blockers:
                        destinations.append(twoStep)
            # Pawns only move diagonally to capture, so diagonals only count for a known capture
            for fileStep in (-1, 1):
                if 0 <= file + fileStep <= 7:
                    diagonal = chess.square(file + fileStep, nextRank)
                    if diagonal == target or (captureAll and diagonal in own):
                        destinations.append(diagonal)
            return destinations

        if pieceType in (chess.KNIGHT, chess.KING):
            attacks = chess.BB_KNIGHT_ATTACKS[square] if pieceType == chess.KNIGHT else chess.BB_KING_ATTACKS[square]
            for destination in chess.scan_forward(attacks):
                if destination in own:
                    if destination == target or captureAll:
                        destinations.append(destination)
                    continue
                if destination not in blockers:
                    destinations.append(destination)
            # Castling: the king jumps two squares if everything between king and rook is empty
            homeRank = 0 if self.enemyColor == chess.WHITE else 7
            if pieceType == chess.KING and square == chess.square(4, homeRank):
                for kingFile, betweenFiles, rookFile in ((6, (5, 6), 7), (2, (1, 2, 3), 0)):
                    rookSquare = chess.square(rookFile, homeRank)
                    between = [chess.square(f, homeRank) for f in betweenFiles]
                    if rookSquare in blockers and not any(s in own or s in blockers for s in between):
                        destinations.append(chess.square(kingFile, homeRank))
            return destinations

        for fileStep, rankStep in SLIDER_DIRECTIONS[pieceType]:
            f, r = file + fileStep, rank + rankStep
            while 0 <= f <= 7 and 0 <= r <= 7:
                destination = chess.square(f, r)
                if destination in own:
                    if destination == target or captureAll:
                        destinations.append(destination)
                    break
                if destination in blockers:
                    break
                destinations.append(destination)
                f, r = f + fileStep, r + rankStep
        return destinations

    # Soft version of _destinations for the prediction step: [(square, probability the move is possible)].
    # otherOccupied[s] is the chance another enemy piece stands on s. Rather than treating a square as either
    # blocked or open, a sliding piece gets past each square with probability 1 - otherOccupied, so a pawn that
    # has probably (but not certainly) moved out of the way leaves a diagonal partly open instead of shut.
    def _moveKernel(self, pieceType, square, own, otherOccupied, target=None):
        kernel = []
        open_ = lambda s: 1.0 - otherOccupied[s]
        file, rank = chess.square_file(square), chess.square_rank(square)

        if pieceType == chess.PAWN:
            step = 1 if self.enemyColor == chess.WHITE else -1
            startRank = 1 if self.enemyColor == chess.WHITE else 6
            nextRank = rank + step
            if not 0 <= nextRank <= 7:
                return kernel
            oneStep = chess.square(file, nextRank)
            if oneStep not in own and open_(oneStep) > 0:
                kernel.append((oneStep, open_(oneStep)))
                if rank == startRank:
                    twoStep = chess.square(file, nextRank + step)
                    if twoStep not in own and open_(twoStep) > 0:
                        kernel.append((twoStep, open_(oneStep) * open_(twoStep)))
            if target is not None:
                for fileStep in (-1, 1):
                    if 0 <= file + fileStep <= 7 and chess.square(file + fileStep, nextRank) == target:
                        kernel.append((target, 1.0))
            return kernel

        if pieceType in (chess.KNIGHT, chess.KING):
            attacks = chess.BB_KNIGHT_ATTACKS[square] if pieceType == chess.KNIGHT else chess.BB_KING_ATTACKS[square]
            for destination in chess.scan_forward(attacks):
                if destination in own:
                    if destination == target:
                        kernel.append((destination, 1.0))
                elif open_(destination) > 0:
                    kernel.append((destination, open_(destination)))
            homeRank = 0 if self.enemyColor == chess.WHITE else 7
            if pieceType == chess.KING and square == chess.square(4, homeRank):
                for kingFile, betweenFiles, rookFile in ((6, (5, 6), 7), (2, (1, 2, 3), 0)):
                    between = [chess.square(f, homeRank) for f in betweenFiles]
                    if any(s in own for s in between):
                        continue
                    chance = otherOccupied[chess.square(rookFile, homeRank)]
                    for s in between:
                        chance *= open_(s)
                    if chance > 0:
                        kernel.append((chess.square(kingFile, homeRank), chance))
            return kernel

        for fileStep, rankStep in SLIDER_DIRECTIONS[pieceType]:
            f, r = file + fileStep, rank + rankStep
            reach = 1.0
            while 0 <= f <= 7 and 0 <= r <= 7 and reach > 1e-3:
                destination = chess.square(f, r)
                if destination in own:
                    if destination == target:
                        kernel.append((destination, reach))
                    break
                if open_(destination) > 0:
                    kernel.append((destination, reach * open_(destination)))
                reach *= open_(destination)
                f, r = f + fileStep, r + rankStep
        return kernel

    #############################
    #   Prediction step
    #############################

    # The enemy made one move. Anything known about it narrows the prediction:
    #   toSquare   - where it landed (a capture of our piece, or a piece seen arriving)
    #   fromSquare - where it left from (a visible piece that moved)
    #   moverTypes - which piece types could have made it
    # With none of these the move was hidden in the fog, and every possible move is considered.
    # ownKing is our king's square, so moves that threaten it can be weighted as more likely.
    def predictionStep(self, ownSquares, toSquare=None, fromSquare=None, moverTypes=None, ownKing=None):
        own = set(ownSquares)
        alive = self.alivePieces()
        if not alive:
            return

        occupied = [0.0] * 64
        for piece in alive:
            for square, probability in enumerate(piece.dist):
                occupied[square] += probability
        likelyOccupied = {s for s in range(64) if occupied[s] >= 0.5}

        # How attractive landing on a square is for a piece type: more so if it attacks our pieces or king
        destinationWeights = {}
        def destinationWeight(pieceType, square):
            key = (pieceType, square)
            if key not in destinationWeights:
                attacked = [s for s in self._destinations(pieceType, square, own, likelyOccupied - {square}, captureAll=True) if s in own]
                weight = 1.0 + THREAT_BONUS * len(attacked)
                if ownKing is not None and ownKing in attacked:
                    weight += KING_THREAT_BONUS
                destinationWeights[key] = weight
            return destinationWeights[key]

        weights, movedDists = [], []
        # First pass uses blockers, second ignores them in case the belief was too confident about blocking pieces
        for ignoreBlockers in (False, True):
            weights, movedDists = [], []
            for piece in alive:
                if moverTypes and piece.pieceType not in moverTypes:
                    weights.append(0.0)
                    movedDists.append(None)
                    continue
                if ignoreBlockers:
                    otherOccupied = [0.0] * 64
                else:
                    otherOccupied = [min(1.0, max(0.0, occupied[s] - piece.dist[s])) for s in range(64)]

                sources = [fromSquare] if fromSquare is not None else range(64)
                weight = 0.0
                moved = [0.0] * 64
                for source in sources:
                    probability = piece.dist[source]
                    if probability <= 0:
                        continue
                    kernel = self._moveKernel(piece.pieceType, source, own, otherOccupied, toSquare)
                    if toSquare is not None:
                        for destination, chance in kernel:
                            if destination == toSquare:
                                weight += probability * chance
                    else:
                        for destination, chance in kernel:
                            moveWeight = probability * chance * destinationWeight(piece.pieceType, destination)
                            moved[destination] += moveWeight
                            weight += moveWeight
                weights.append(weight * MOVER_TYPE_WEIGHT[piece.pieceType])
                movedDists.append(moved)
            if sum(weights) > 0:
                break

        total = sum(weights)
        if total <= 0:
            if toSquare is None:
                return  # No enemy piece can move at all, nothing changes
            # We know a move happened on toSquare but no tracked piece could make it: the belief lost track.
            # Spread the blame evenly over every piece that matches.
            candidates = [p for p in alive if not moverTypes or p.pieceType in moverTypes] or alive
            weights = [1.0 if p in candidates else 0.0 for p in alive]
            total = float(len(candidates))

        for piece, weight, moved in zip(alive, weights, movedDists):
            moverProbability = weight / total
            if moverProbability <= 0:
                continue
            if toSquare is not None:
                arrival = [0.0] * 64
                arrival[toSquare] = 1.0
            else:
                movedTotal = sum(moved)
                arrival = [m / movedTotal for m in moved]
            # P(new square) = P(did not move) * P(old square) + P(moved) * P(arrived here)
            piece.dist = [(1 - moverProbability) * old + moverProbability * new for old, new in zip(piece.dist, arrival)]
            self._normalise(piece)

    #############################
    #   Observation step
    #############################

    # visibleSquares - every square we can currently see
    # visibleEnemy   - {square: pieceType} for every enemy piece we can currently see
    # ownSquares     - squares holding our own pieces (an enemy piece can't be there either)
    def observationStep(self, visibleSquares, visibleEnemy, ownSquares=()):
        visible = set(visibleSquares) | set(visibleEnemy)
        excluded = visible | set(ownSquares)

        assigned = self._associate(visibleEnemy)
        for square, piece in assigned.items():
            piece.dist = [0.0] * 64
            piece.dist[square] = 1.0

        assignedIds = {id(piece) for piece in assigned.values()}
        for piece in self.alivePieces():
            if id(piece) in assignedIds:
                continue
            # Every square we can see either is empty or holds a different piece, so this piece is not there
            for square in excluded:
                piece.dist[square] = 0.0
            self._normalise(piece, excluded)

        self._enforceExclusion(excluded)

    # Data association: decide which tracked piece is the one we are looking at on each visible square.
    # Pairs are taken greedily, most probable first, so a piece we were sure about keeps its identity.
    def _associate(self, visibleEnemy):
        alive = self.alivePieces()
        pairs = []
        for square, pieceType in visibleEnemy.items():
            for piece in alive:
                if piece.pieceType == pieceType and piece.dist[square] > 0:
                    pairs.append((piece.dist[square], square, piece))
        pairs.sort(key=lambda pair: -pair[0])

        assigned, used = {}, set()
        for _, square, piece in pairs:
            if square in assigned or id(piece) in used:
                continue
            assigned[square] = piece
            used.add(id(piece))

        # Squares no tracked piece could explain: either the filter lost track of a piece, or a pawn promoted
        for square, pieceType in visibleEnemy.items():
            if square in assigned:
                continue
            color = isLightSquare(square)
            candidates = [p for p in alive if p.pieceType == pieceType and id(p) not in used
                          and (pieceType != chess.BISHOP or p.squareColor in (None, color))]
            if candidates:
                piece = min(candidates, key=lambda p: p.certainty())   # The piece we knew least about
            else:
                pawns = [p for p in alive if p.pieceType == chess.PAWN and id(p) not in used]
                if pawns and pieceType not in (chess.PAWN, chess.KING):
                    piece = max(pawns, key=self._promotionScore)
                    piece.pieceType = pieceType
                    piece.squareColor = None
                else:
                    piece = TrackedPiece(pieceType)
                    self.pieces.append(piece)
            assigned[square] = piece
            used.add(id(piece))
        return assigned

    # How far up the board a pawn is expected to be, used to guess which pawn promoted
    def _promotionScore(self, pawn):
        if self.enemyColor == chess.WHITE:
            return sum(p * chess.square_rank(s) for s, p in enumerate(pawn.dist))
        return sum(p * (7 - chess.square_rank(s)) for s, p in enumerate(pawn.dist))

    # Two pieces can't share a square: a piece we are certain about removes that square from everyone else
    def _enforceExclusion(self, excluded):
        alive = self.alivePieces()
        for _ in range(4):
            certainSquares = {}
            for piece in alive:
                square = piece.mostLikelySquare()
                if piece.dist[square] >= CERTAIN:
                    certainSquares[square] = piece
            changed = False
            for piece in alive:
                touched = False
                for square, owner in certainSquares.items():
                    if owner is not piece and piece.dist[square] > 0:
                        piece.dist[square] = 0.0
                        touched = True
                if touched:
                    changed = True
                    self._normalise(piece, set(excluded) | set(certainSquares))
            if not changed:
                break

    def _validSquare(self, piece, square):
        if piece.pieceType == chess.PAWN and chess.square_rank(square) in (0, 7):
            return False
        if piece.squareColor is not None and isLightSquare(square) != piece.squareColor:
            return False
        return True

    # Rescale a grid to sum to 1. If every square was ruled out the filter has lost the piece completely,
    # so start it over spread evenly across every square it could still be hiding on.
    def _normalise(self, piece, excluded=()):
        total = sum(piece.dist)
        if total > 1e-12:
            piece.dist = [p / total for p in piece.dist]
            return
        options = [s for s in range(64) if s not in excluded and self._validSquare(piece, s)]
        if not options:
            options = [s for s in range(64) if s not in excluded] or list(range(64))
        piece.dist = [0.0] * 64
        for square in options:
            piece.dist[square] = 1.0 / len(options)

    #############################
    #   Updates from our own moves
    #############################

    # We captured the enemy piece on `square`. Returns the tracked piece removed
    def removePieceAt(self, square, pieceType=None):
        candidates = [p for p in self.alivePieces() if pieceType is None or p.pieceType == pieceType]
        if not candidates:
            candidates = self.alivePieces()
        if not candidates:
            return None
        piece = max(candidates, key=lambda p: p.dist[square])
        piece.alive = False
        self.capturedPieces[piece.pieceType] += 1
        return piece

    # Our pieces now stand on these squares, so no enemy piece can be there
    def markOccupiedByUs(self, squares):
        squares = set(squares)
        for piece in self.alivePieces():
            if any(piece.dist[s] > 0 for s in squares):
                for square in squares:
                    piece.dist[square] = 0.0
                self._normalise(piece, squares)

    # An enemy piece was seen going from one square to another (used for the rook half of castling)
    def forceMove(self, fromSquare, toSquare, pieceType=None):
        candidates = [p for p in self.alivePieces() if pieceType is None or p.pieceType == pieceType]
        if not candidates:
            return
        piece = max(candidates, key=lambda p: p.dist[fromSquare])
        piece.dist = [0.0] * 64
        piece.dist[toSquare] = 1.0

    # The pawn that just reached `square` became a new piece
    def promoteAt(self, square, newType):
        pawns = [p for p in self.alivePieces() if p.pieceType == chess.PAWN]
        if pawns:
            pawn = max(pawns, key=lambda p: p.dist[square])
            if pawn.dist[square] > 0:
                pawn.pieceType = newType
                pawn.squareColor = None

    #############################
    #   Boards for the search
    #############################

    # Build a full chess.Board from the belief: our pieces copied from ownBoard, enemy pieces placed from their grids.
    # mode "map" picks each piece's most likely square, mode "sample" draws a random square from its grid.
    # Pieces we are most certain of are placed first so they get their square before the guesses do.
    def sampleBoard(self, ownBoard, mode="sample", rng=random):
        board = chess.Board(None)
        occupied = set()
        for square, piece in ownBoard.piece_map().items():
            if piece.color == self.color:
                board.set_piece_at(square, piece)
                occupied.add(square)

        for piece in sorted(self.alivePieces(), key=lambda p: -p.certainty()):
            weights = [0.0 if s in occupied else p for s, p in enumerate(piece.dist)]
            if sum(weights) <= 0:
                options = [s for s in range(64) if s not in occupied and self._validSquare(piece, s)]
                if not options:
                    continue
                square = options[0] if mode == "map" else rng.choice(options)
            elif mode == "map":
                square = max(range(64), key=weights.__getitem__)
            else:
                square = rng.choices(range(64), weights=weights)[0]

            pieceType = piece.pieceType
            if pieceType == chess.PAWN and chess.square_rank(square) == self._promotionRank():
                pieceType = chess.QUEEN  # A pawn that reached the end has promoted, almost always to a queen
            board.set_piece_at(square, chess.Piece(pieceType, self.enemyColor))
            occupied.add(square)

        board.turn = self.color
        return board

    def mostLikelyBoard(self, ownBoard):
        return self.sampleBoard(ownBoard, mode="map")
