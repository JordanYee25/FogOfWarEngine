import copy
import platform
import sys
import threading
import time

import chess
import pygame

import config
from engine import FogEngine

# Fog of War Assistant
#
# Play a Fog of War game somewhere else (a website, over the board with a referee) and use this window as your
# engine. You enter what happens and the engine tells you what it would play:
#
#   Your turn      - the engine suggests a move. Play it (or any move you like) by clicking it on this board.
#   What you saw   - if your move uncovered new squares, mark any enemy pieces you can now see.
#   Their turn     - once your opponent has moved, make the enemy pieces here match your screen.
#                    Nothing changed? Just press "Opponent moved": the move was hidden in the fog.
#
# Everything here is from your side's point of view: you only ever enter what you could really see.

SQ = 80
BOARD = SQ * 8
MARGIN = 28
PANEL_X = BOARD + MARGIN * 2
PANEL_W = 420
WIDTH = PANEL_X + PANEL_W
HEIGHT = BOARD + MARGIN * 2

LIGHT = config.SQUARECOLOR_LIGHT
DARK = config.SQUARECOLOR_DARK
PANEL_BG = (30, 32, 38)
CARD_BG = (42, 45, 53)
TEXT = (232, 233, 238)
MUTED = (150, 155, 168)
ACCENT = (86, 156, 255)
GOOD = (96, 200, 128)
WARN = (240, 176, 64)
BAD = (232, 88, 88)
FOG = (38, 40, 48, 178)
HEAT = (196, 52, 48)

SETUP, OURS, SIGHTINGS, THEIRS, OVER = "setup", "ours", "sightings", "theirs", "over"

FILLED = {chess.KING: "♚", chess.QUEEN: "♛", chess.ROOK: "♜", chess.BISHOP: "♝", chess.KNIGHT: "♞", chess.PAWN: "♟"}
OUTLINE = {chess.KING: "♔", chess.QUEEN: "♕", chess.ROOK: "♖", chess.BISHOP: "♗", chess.KNIGHT: "♘", chess.PAWN: "♙"}
PALETTE = [chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN, chess.KING]
PALETTE_KEYS = {pygame.K_p: chess.PAWN, pygame.K_n: chess.KNIGHT, pygame.K_b: chess.BISHOP,
                pygame.K_r: chess.ROOK, pygame.K_q: chess.QUEEN, pygame.K_k: chess.KING}
ERASER = "eraser"


class Draft:
    """The board as the user is editing it, before it is handed to the engine."""

    def __init__(self, engine):
        self.enemies = engine.reportedEnemies()
        self.captured = set()
        self.blocked = set(engine.blocked)


class App:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("Fog of War Assistant")
        self.clock = pygame.time.Clock()
        self.fonts = {}

        self.thinkTime = config.ENGINE_THINK_TIME
        self.showHeat = True
        self.showGhosts = True
        self.flipped = False
        self.engine = None
        self.phase = SETUP
        self.undoStack = []
        self.results = []           # Finished searches from the background thread: (generation, suggestions)
        self.searchGen = 0
        self.buttons = []
        self.hover = None
        self.mouse = (0, 0)
        self.confirmNew = False
        self.message = ""
        self.lastOurMove = None
        self.lastReport = None
        self.newlyVisible = set()
        self.resetTurnState()

    #############################
    #   Helpers
    #############################

    def font(self, size, bold=False, symbol=False):
        key = (size, bold, symbol)
        if key not in self.fonts:
            if symbol:
                name = {"Windows": "segoeuisymbol", "Darwin": "applesymbols"}.get(platform.system(), "dejavusans")
            else:
                name = {"Windows": "segoeui", "Darwin": "helveticaneue"}.get(platform.system(), "dejavusans")
            self.fonts[key] = pygame.font.SysFont(name, size, bold=bold)
        return self.fonts[key]

    def resetTurnState(self):
        self.selected = None
        self.promotionChoices = None
        self.suggestions = None
        self.highlight = 0
        self.thinking = False
        self.thinkStarted = 0
        self.draft = None
        self.tool = None
        self.drag = None
        self.visible = set()
        self.preview = None
        self.candidates = []

    def whiteBottom(self):
        ours = self.engine.color if self.engine else chess.WHITE
        return (ours == chess.WHITE) != self.flipped

    def squareRect(self, square):
        file, rank = chess.square_file(square), chess.square_rank(square)
        col, row = (file, 7 - rank) if self.whiteBottom() else (7 - file, rank)
        return pygame.Rect(MARGIN + col * SQ, MARGIN + row * SQ, SQ, SQ)

    def squareAt(self, pos):
        x, y = pos[0] - MARGIN, pos[1] - MARGIN
        if not (0 <= x < BOARD and 0 <= y < BOARD):
            return None
        col, row = int(x // SQ), int(y // SQ)
        return chess.square(col, 7 - row) if self.whiteBottom() else chess.square(7 - col, row)

    def text(self, string, pos, size=16, color=TEXT, bold=False, center=False, right=False):
        surface = self.font(size, bold).render(string, True, color)
        rect = surface.get_rect()
        if center:
            rect.center = pos
        elif right:
            rect.topright = pos
        else:
            rect.topleft = pos
        self.screen.blit(surface, rect)
        return rect

    def wrapped(self, string, x, y, width, size=15, color=TEXT, bold=False, lineGap=3):
        font = self.font(size, bold)
        for paragraph in string.split("\n"):
            line = ""
            for word in paragraph.split(" "):
                attempt = (line + " " + word).strip()
                if font.size(attempt)[0] > width and line:
                    self.screen.blit(font.render(line, True, color), (x, y))
                    y += font.get_linesize() + lineGap
                    line = word
                else:
                    line = attempt
            self.screen.blit(font.render(line, True, color), (x, y))
            y += font.get_linesize() + lineGap
        return y

    def button(self, rect, label, action, style="normal", enabled=True, selected=False, size=15):
        rect = pygame.Rect(rect)
        hovered = rect.collidepoint(self.mouse) and enabled
        if style == "primary":
            fill = (70, 140, 240) if hovered else ACCENT
            textColor = (255, 255, 255)
        else:
            fill = (66, 70, 82) if hovered else (52, 56, 66)
            textColor = TEXT
        if selected:
            fill = (88, 120, 180)
        if not enabled:
            fill, textColor = (44, 46, 54), (100, 104, 116)
        pygame.draw.rect(self.screen, fill, rect, border_radius=7)
        if selected:
            pygame.draw.rect(self.screen, (160, 196, 255), rect, 2, border_radius=7)
        self.text(label, rect.center, size, textColor, bold=(style == "primary"), center=True)
        if enabled:
            self.buttons.append((rect, action))
        return rect

    def drawPiece(self, surface, pieceType, color, center, size=int(SQ * 0.78), alpha=255):
        font = self.font(size, symbol=True)
        fill = font.render(FILLED[pieceType], True, (250, 250, 250) if color == chess.WHITE else (28, 28, 30))
        outline = font.render(OUTLINE[pieceType] if color == chess.WHITE else FILLED[pieceType], True, (20, 20, 22))
        for glyph in (fill, outline):
            glyph.set_alpha(alpha)
            surface.blit(glyph, glyph.get_rect(center=center))

    #############################
    #   Game flow
    #############################

    def newGame(self, color):
        self.engine = FogEngine(color, thinkTime=self.thinkTime, numSamples=config.ENGINE_SAMPLES)
        self.undoStack = []
        self.lastOurMove = None
        self.lastReport = None
        self.newlyVisible = set()
        self.flipped = False
        self.message = ""
        self.enterPhase(OURS if color == chess.WHITE else THEIRS)

    def enterPhase(self, phase):
        self.searchGen += 1         # Any search still running belongs to an old position
        self.resetTurnState()
        self.phase = phase
        if phase == OURS:
            self.candidates = self.engine.candidateMoves()
            self.startThinking()
        if phase in (SIGHTINGS, THEIRS):
            self.draft = Draft(self.engine)
            self.refreshDraft()
        if phase in (OURS, OVER):
            self.visible = self.engine.visibleSquares()
        self.refreshBelief()

    def startThinking(self):
        self.searchGen += 1
        generation = self.searchGen
        self.suggestions = None
        self.thinking = True
        self.thinkStarted = time.time()
        job = self.engine.prepareSearch(self.thinkTime)

        def run():
            self.results.append((generation, job.run()))
        threading.Thread(target=run, daemon=True).start()

    def pushUndo(self):
        self.undoStack.append((copy.deepcopy(self.engine), self.phase, set(self.newlyVisible), self.lastOurMove, self.lastReport))

    def undo(self):
        if not self.undoStack:
            self.message = "Nothing to undo"
            return
        self.engine, phase, self.newlyVisible, self.lastOurMove, self.lastReport = self.undoStack.pop()
        self.message = "Undone"
        self.enterPhase(phase)

    def commitOurMove(self, move):
        self.pushUndo()
        visibleBefore = self.engine.visibleSquares()
        self.engine.applyOurMove(move)
        self.lastOurMove = move
        self.lastReport = None
        self.message = ""
        if self.engine.result:
            self.enterPhase(OVER)
            return
        self.newlyVisible = self.engine.visibleSquares() - visibleBefore - self.engine.ownSquares()
        self.enterPhase(SIGHTINGS if self.newlyVisible else THEIRS)

    def confirmSightings(self):
        self.pushUndo()
        self.engine.applySightings(self.draft.enemies, self.draft.blocked)
        self.enterPhase(THEIRS)

    def submitOpponentMove(self):
        self.pushUndo()
        self.lastReport = self.engine.applyOpponentMove(self.draft.enemies, self.draft.captured, self.draft.blocked)
        self.lastOurMove = None
        self.newlyVisible = set()
        self.enterPhase(OVER if self.engine.result else OURS)

    def refreshDraft(self):
        draft = self.draft
        self.visible = self.engine.visibleSquares(draft.enemies, draft.captured, draft.blocked)
        if self.phase == THEIRS:
            self.preview = self.engine.interpretOpponentMove(draft.enemies, draft.captured, draft.blocked)
        else:
            self.preview = None

    def refreshBelief(self):
        if not self.engine:
            self.occupancy, self.ghosts = [0.0] * 64, {}
            return
        belief = self.engine.belief
        self.occupancy = belief.occupancy()
        self.ghosts = {}
        for square in range(64):
            breakdown = belief.squareBreakdown(square)
            if breakdown:
                pieceType, probability = max(breakdown.items(), key=lambda item: item[1])
                self.ghosts[square] = (pieceType, probability)

    #############################
    #   Board editing (sightings and their turn)
    #############################

    def ownPieceAt(self, square):
        piece = self.engine.board.piece_at(square)
        return piece is not None and piece.color == self.engine.color

    def placeEnemy(self, square, pieceType):
        draft = self.draft
        if self.ownPieceAt(square):
            if self.phase != THEIRS:
                self.message = "Your pieces can only be captured on the opponent's turn"
                return
            draft.captured.add(square)
        draft.enemies[square] = pieceType
        draft.blocked.discard(square)
        self.refreshDraft()

    def eraseAt(self, square):
        draft = self.draft
        if square in draft.enemies:
            del draft.enemies[square]
        elif square in draft.captured:
            draft.captured.discard(square)
        elif self.ownPieceAt(square):
            if self.phase == THEIRS:
                draft.captured.add(square)
            else:
                self.message = "Your pieces can only be captured on the opponent's turn"
        elif square in self.engine.pawnPushSquares():
            draft.blocked.symmetric_difference_update({square})
        else:
            self.message = "Nothing to remove there"
        self.refreshDraft()

    #############################
    #   Input
    #############################

    def handleKey(self, event):
        key, mods = event.key, event.mod
        if key == pygame.K_z and mods & pygame.KMOD_CTRL or key == pygame.K_u:
            if self.phase != SETUP:
                self.undo()
            return
        if key == pygame.K_h:
            self.showHeat = not self.showHeat
        elif key == pygame.K_g:
            self.showGhosts = not self.showGhosts
        elif key == pygame.K_f:
            self.flipped = not self.flipped
        elif key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
            self.thinkTime = min(30.0, self.thinkTime + 1.0)
        elif key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self.thinkTime = max(1.0, self.thinkTime - 1.0)
        elif key == pygame.K_ESCAPE:
            self.selected, self.promotionChoices, self.tool = None, None, None

        if self.phase == SETUP:
            if key == pygame.K_w:
                self.newGame(chess.WHITE)
            elif key == pygame.K_b:
                self.newGame(chess.BLACK)
        elif self.phase == OURS:
            if self.promotionChoices and key in PALETTE_KEYS:
                for move in self.promotionChoices:
                    if move.promotion == PALETTE_KEYS[key]:
                        self.commitOurMove(move)
                        return
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER) and self.suggestions:
                self.commitOurMove(self.suggestions[self.highlight].move)
            elif key == pygame.K_TAB and self.suggestions:
                self.highlight = (self.highlight + 1) % len(self.suggestions)
        elif self.phase in (SIGHTINGS, THEIRS):
            if key in PALETTE_KEYS:
                self.tool = PALETTE_KEYS[key]
            elif key == pygame.K_e:
                self.tool = ERASER
            elif key == pygame.K_m:
                self.tool = None
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                if self.phase == SIGHTINGS:
                    self.confirmSightings()
                else:
                    self.submitOpponentMove()
        elif self.phase == OVER and key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.runAction("newgame")

    def handleMouseDown(self, event):
        if event.button == 1:
            for rect, action in self.buttons:
                if rect.collidepoint(event.pos):
                    if action != "newgame":
                        self.confirmNew = False
                    self.runAction(action)
                    return
        self.confirmNew = False
        square = self.squareAt(event.pos)
        if square is None or self.engine is None:
            return

        if self.phase == OURS:
            if event.button == 3:
                self.selected = None
                return
            if self.selected is not None:
                moves = [m for m in self.candidates if m.from_square == self.selected and m.to_square == square]
                if len(moves) > 1:
                    self.promotionChoices = moves
                    return
                if moves:
                    self.commitOurMove(moves[0])
                    return
            self.promotionChoices = None
            self.selected = square if any(m.from_square == square for m in self.candidates) else None

        elif self.phase in (SIGHTINGS, THEIRS):
            if event.button == 3 or self.tool == ERASER:
                self.eraseAt(square)
            elif self.tool is not None:
                self.placeEnemy(square, self.tool)
            elif square in self.draft.enemies:
                self.drag = (square, self.draft.enemies[square])
            elif self.ownPieceAt(square):
                self.message = "Right-click your piece if it was captured"
            else:
                self.message = "Pick an enemy piece from the palette to place it"

    def handleMouseUp(self, event):
        if event.button != 1 or self.drag is None:
            return
        origin, pieceType = self.drag
        self.drag = None
        square = self.squareAt(event.pos)
        if square is None:
            del self.draft.enemies[origin]      # Dragged off the board: remove it
            self.refreshDraft()
        elif square != origin:
            del self.draft.enemies[origin]
            self.placeEnemy(square, pieceType)

    def runAction(self, action):
        kind = action[0] if isinstance(action, tuple) else action
        if kind == "color":
            self.newGame(action[1])
        elif kind == "play":
            self.commitOurMove(action[1])
        elif kind == "highlight":
            self.highlight = action[1]
        elif kind == "rethink":
            self.startThinking()
        elif kind == "time":
            self.thinkTime = max(1.0, min(30.0, self.thinkTime + action[1]))
        elif kind == "tool":
            self.tool = action[1]
        elif kind == "sightings":
            self.confirmSightings()
        elif kind == "submit":
            self.submitOpponentMove()
        elif kind == "resetDraft":
            self.draft = Draft(self.engine)
            self.refreshDraft()
        elif kind == "toggle":
            setattr(self, action[1], not getattr(self, action[1]))
        elif kind == "undo":
            self.undo()
        elif kind == "newgame":
            if self.confirmNew or self.phase in (SETUP, OVER):
                self.confirmNew = False
                self.searchGen += 1
                self.engine = None
                self.phase = SETUP
                self.resetTurnState()
                self.refreshBelief()
            else:
                self.confirmNew = True

    #############################
    #   Drawing: board
    #############################

    def drawBoard(self):
        engine = self.engine
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        visible = self.visible if engine else set(chess.SQUARES)

        for square in chess.SQUARES:
            rect = self.squareRect(square)
            light = (chess.square_file(square) + chess.square_rank(square)) % 2 == 1
            pygame.draw.rect(self.screen, LIGHT if light else DARK, rect)
            if engine and square not in visible:
                # Fog, tinted red by how likely an enemy piece hides there (blended here: pygame.draw doesn't blend)
                heat = min(1.0, self.occupancy[square]) * 0.85 if self.showHeat else 0.0
                color = tuple(int(f + (h - f) * heat) for f, h in zip(FOG[:3], HEAT)) + (FOG[3],)
                pygame.draw.rect(overlay, color, rect)

        if self.lastOurMove:
            for square in (self.lastOurMove.from_square, self.lastOurMove.to_square):
                pygame.draw.rect(overlay, (250, 220, 80, 80), self.squareRect(square))
        if self.phase == SIGHTINGS:
            for square in self.newlyVisible:
                pygame.draw.rect(overlay, (255, 214, 64, 230), self.squareRect(square).inflate(-4, -4), 3, border_radius=4)
        if self.preview and self.phase == THEIRS:
            for square in (self.preview.fromSquare, self.preview.toSquare):
                if square is not None:
                    pygame.draw.rect(overlay, (86, 156, 255, 220), self.squareRect(square).inflate(-4, -4), 3, border_radius=4)
        self.screen.blit(overlay, (0, 0))

        if engine:
            self.drawPieces()
        self.drawCoordinates()

    def drawPieces(self):
        engine = self.engine
        draft = self.draft
        enemies = draft.enemies if draft else engine.reportedEnemies()
        captured = draft.captured if draft else set()
        blocked = draft.blocked if draft else engine.blocked

        # Ghosts: the belief state's best guess for what hides in each fogged square
        if self.showGhosts:
            for square, (pieceType, probability) in self.ghosts.items():
                if square in self.visible or square in enemies or probability < 0.15:
                    continue
                rect = self.squareRect(square)
                self.drawPiece(self.screen, pieceType, engine.enemyColor, rect.center, int(SQ * 0.6), int(50 + 150 * probability))
                self.text(f"{round(probability * 100)}%", (rect.right - 4, rect.bottom - 18), 12, (235, 235, 240), right=True)

        for square, piece in engine.board.piece_map().items():
            if piece.color != engine.color or square in enemies:
                continue
            rect = self.squareRect(square)
            if square == self.selected:
                pygame.draw.rect(self.screen, (250, 220, 80), rect, 4)
            self.drawPiece(self.screen, piece.piece_type, piece.color, rect.center, alpha=90 if square in captured else 255)
            if square in captured:
                self.drawCross(rect, BAD)

        for square, pieceType in enemies.items():
            if self.drag and self.drag[0] == square:
                continue
            rect = self.squareRect(square)
            ignored = square not in self.visible
            self.drawPiece(self.screen, pieceType, engine.enemyColor, rect.center, alpha=110 if ignored else 255)
            if square in captured:
                pygame.draw.rect(self.screen, BAD, rect.inflate(-4, -4), 3, border_radius=4)
            if ignored:
                self.text("?", (rect.right - 12, rect.top + 4), 18, BAD, bold=True)

        for square in blocked:
            rect = self.squareRect(square)
            pygame.draw.rect(self.screen, WARN, rect.inflate(-10, -10), 2, border_radius=6)
            self.text("blocked", rect.center, 13, WARN, bold=True, center=True)

        if self.phase == OURS:
            self.drawSuggestionArrows()
            if self.selected is not None:
                for move in self.candidates:
                    if move.from_square == self.selected:
                        rect = self.squareRect(move.to_square)
                        dot = pygame.Surface((SQ, SQ), pygame.SRCALPHA)
                        pygame.draw.circle(dot, (40, 40, 40, 140), (SQ // 2, SQ // 2), SQ // 7)
                        self.screen.blit(dot, rect)

        if self.drag:
            self.drawPiece(self.screen, self.drag[1], engine.enemyColor, self.mouse)

    def drawCross(self, rect, color):
        inner = rect.inflate(-22, -22)
        pygame.draw.line(self.screen, color, inner.topleft, inner.bottomright, 5)
        pygame.draw.line(self.screen, color, inner.bottomleft, inner.topright, 5)

    def drawSuggestionArrows(self):
        if not self.suggestions:
            return
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        for index, suggestion in reversed(list(enumerate(self.suggestions[:3]))):
            main = index == self.highlight
            color = (40, 150, 255, 210) if main else (40, 150, 255, 90)
            self.drawArrow(overlay, suggestion.move, color, 14 if main else 8)
        self.screen.blit(overlay, (0, 0))

    def drawArrow(self, surface, move, color, width):
        start = pygame.Vector2(self.squareRect(move.from_square).center)
        end = pygame.Vector2(self.squareRect(move.to_square).center)
        direction = end - start
        if direction.length() == 0:
            return
        unit = direction.normalize()
        head = width * 2.2
        shaftEnd = end - unit * head
        perpendicular = pygame.Vector2(-unit.y, unit.x)
        pygame.draw.line(surface, color, start, shaftEnd, width)
        pygame.draw.polygon(surface, color, [end, shaftEnd + perpendicular * head * 0.75, shaftEnd - perpendicular * head * 0.75])

    def drawCoordinates(self):
        for i in range(8):
            file = i if self.whiteBottom() else 7 - i
            rank = 7 - i if self.whiteBottom() else i
            self.text(chess.FILE_NAMES[file], (MARGIN + i * SQ + SQ // 2, MARGIN + BOARD + 13), 13, MUTED, center=True)
            self.text(chess.RANK_NAMES[rank], (MARGIN // 2, MARGIN + i * SQ + SQ // 2), 13, MUTED, center=True)

    #############################
    #   Drawing: panel
    #############################

    def drawPanel(self):
        pygame.draw.rect(self.screen, PANEL_BG, (PANEL_X - 8, 0, PANEL_W + 8, HEIGHT))
        x, width = PANEL_X + 12, PANEL_W - 36
        self.text("Fog of War Assistant", (x, 16), 22, TEXT, bold=True)
        y = 50
        if self.engine:
            side = "White" if self.engine.color == chess.WHITE else "Black"
            moveNumber = len(self.engine.moveLog) // 2 + 1
            known = self.engine.belief.knownPieceCount()
            alive = len(self.engine.belief.alivePieces())
            self.text(f"You play {side}  ·  move {moveNumber}  ·  enemy pieces located {known}/{alive}", (x, y), 14, MUTED)
        y += 30

        if self.phase == SETUP:
            y = self.drawSetup(x, y, width)
        elif self.phase == OURS:
            y = self.drawOurTurn(x, y, width)
        elif self.phase == SIGHTINGS:
            y = self.drawEditing(x, y, width, sightings=True)
        elif self.phase == THEIRS:
            y = self.drawEditing(x, y, width, sightings=False)
        elif self.phase == OVER:
            y = self.drawOver(x, y, width)

        if self.message:
            self.text(self.message, (x, HEIGHT - 150), 14, WARN)
        self.drawHover(x, HEIGHT - 128)
        self.drawFooter(x, width)

    def drawSetup(self, x, y, width):
        y = self.wrapped("Use this engine while you play a Fog of War game somewhere else. You enter what you see, "
                         "and it suggests your moves using a belief state of where the hidden enemy pieces probably are.",
                         x, y, width, 15, MUTED)
        y += 14
        self.text("Which colour are you playing?", (x, y), 17, TEXT, bold=True)
        y += 34
        self.button((x, y, width // 2 - 6, 46), "White  (W)", ("color", chess.WHITE), "primary")
        self.button((x + width // 2 + 6, y, width // 2 - 6, 46), "Black  (B)", ("color", chess.BLACK), "primary")
        y += 66
        y = self.drawThinkTime(x, y)
        y += 16
        y = self.wrapped("How a turn works", x, y, width, 16, TEXT, bold=True)
        y = self.wrapped("1. Your turn: play the suggested move, or click any move on the board.\n"
                         "2. If your move uncovered new squares, mark the enemy pieces you can now see.\n"
                         "3. Their turn: when they've moved, make the enemy pieces match your screen and press "
                         "Opponent moved. If nothing changed, just press it: their move was hidden in the fog.",
                         x, y + 4, width, 14, MUTED)
        return y

    def drawThinkTime(self, x, y):
        self.text(f"Think time: {self.thinkTime:.0f}s", (x, y + 6), 15, TEXT)
        self.button((x + 150, y, 34, 30), "-", ("time", -1.0))
        self.button((x + 190, y, 34, 30), "+", ("time", 1.0))
        return y + 40

    def drawOurTurn(self, x, y, width):
        self.text("Your move", (x, y), 20, GOOD, bold=True)
        y += 34
        if self.lastReport:
            y = self.wrapped("Last: " + "; ".join(self.lastReport.description), x, y, width, 14, MUTED)
            y += 6

        if self.promotionChoices:
            self.text("Promote to:", (x, y), 16, TEXT, bold=True)
            y += 28
            for i, move in enumerate(sorted(self.promotionChoices, key=lambda m: -m.promotion)):
                name = chess.piece_name(move.promotion).capitalize()
                self.button((x + i * (width // 4), y, width // 4 - 6, 36), name, ("play", move))
            return y + 50

        card = pygame.Rect(x - 6, y, width + 12, 200)
        pygame.draw.rect(self.screen, CARD_BG, card, border_radius=10)
        cy = y + 10
        if self.thinking:
            dots = "." * (int(time.time() * 3) % 4)
            self.text(f"Thinking{dots}", (x + 6, cy), 17, TEXT, bold=True)
            elapsed = min(1.0, (time.time() - self.thinkStarted) / max(0.1, self.thinkTime * 1.3))
            pygame.draw.rect(self.screen, (60, 64, 76), (x + 6, cy + 34, width - 12, 6), border_radius=3)
            pygame.draw.rect(self.screen, ACCENT, (x + 6, cy + 34, int((width - 12) * elapsed), 6), border_radius=3)
        elif not self.suggestions:
            self.text("No moves available", (x + 6, cy), 16, MUTED)
        else:
            self.text("Engine suggests", (x + 6, cy), 14, MUTED)
            cy += 24
            for index, suggestion in enumerate(self.suggestions[:4]):
                row = pygame.Rect(x, cy, width, 36)
                if index == self.highlight:
                    pygame.draw.rect(self.screen, (60, 78, 112), row, border_radius=6)
                self.buttons.append((row, ("highlight", index)))
                self.text(f"{index + 1}.", (x + 8, cy + 7), 16, MUTED)
                self.text(suggestion.label, (x + 34, cy + 5), 19, TEXT, bold=True)
                score = suggestion.score / 100
                self.text(f"{score:+.1f}", (x + 150, cy + 8), 15, GOOD if score >= 0 else BAD)
                details = f"{suggestion.votes}/{suggestion.samples} boards"
                risk = max(suggestion.danger, suggestion.kingLoss / max(1, suggestion.samples))
                if risk >= 0.05:
                    details += f"   king risk {round(risk * 100)}%"
                self.text(details, (x + 210, cy + 9), 13, WARN if risk >= 0.05 else MUTED)
                cy += 38
        y = card.bottom + 12

        best = self.suggestions[self.highlight] if self.suggestions else None
        self.button((x, y, width - 120, 42), f"Play {best.label}  (Enter)" if best else "Play", ("play", best.move) if best else None,
                    "primary", enabled=best is not None)
        self.button((x + width - 110, y, 110, 42), "Re-think", "rethink", enabled=not self.thinking)
        y += 56
        y = self.drawThinkTime(x, y)
        y = self.wrapped("Played something else? Click your piece, then its square. Tab cycles suggestions.",
                         x, y + 4, width, 14, MUTED)
        return y

    def drawPalette(self, x, y, width):
        size = 46
        for i, pieceType in enumerate(PALETTE):
            rect = pygame.Rect(x + i * (size + 6), y, size, size)
            selected = self.tool == pieceType
            pygame.draw.rect(self.screen, (88, 120, 180) if selected else (52, 56, 66), rect, border_radius=7)
            if selected:
                pygame.draw.rect(self.screen, (160, 196, 255), rect, 2, border_radius=7)
            self.drawPiece(self.screen, pieceType, self.engine.enemyColor, rect.center, 38)
            self.buttons.append((rect, ("tool", pieceType)))
        bx = x + 6 * (size + 6)
        self.button((bx, y, width - (bx - x), size // 2 - 2), "Move (M)", ("tool", None), selected=self.tool is None, size=13)
        self.button((bx, y + size // 2 + 2, width - (bx - x), size // 2 - 2), "Erase (E)", ("tool", ERASER),
                    selected=self.tool == ERASER, size=13)
        return y + size + 10

    def drawEditing(self, x, y, width, sightings):
        if sightings:
            self.text("What did your move reveal?", (x, y), 20, WARN, bold=True)
            y += 34
            y = self.wrapped(f"Your move uncovered {len(self.newlyVisible)} new square(s), outlined in yellow. "
                             "Place any enemy pieces you can now see, then confirm. Nothing there? Just press Enter.",
                             x, y, width, 14, MUTED)
        else:
            self.text("Opponent's move", (x, y), 20, ACCENT, bold=True)
            y += 34
            y = self.wrapped("When they have moved, make the enemy pieces here match your screen: drag pieces that moved, "
                             "place new ones from the palette, right-click to remove. Right-click your own piece if it "
                             "was captured. If nothing visible changed, just press Enter: the move was hidden.",
                             x, y, width, 14, MUTED)
        y += 8
        y = self.drawPalette(x, y, width)
        y = self.wrapped("Keys: P N B R Q K pick a piece. A square in front of your pawn that is fogged on your screen "
                         "has something on it: right-click it to mark it blocked.", x, y, width, 12, MUTED, lineGap=1)
        y += 6

        card = pygame.Rect(x - 6, y, width + 12, 92)
        pygame.draw.rect(self.screen, CARD_BG, card, border_radius=10)
        cy = y + 8
        if sightings:
            count = len([s for s in self.draft.enemies if s in self.visible])
            self.text(f"{count} enemy piece(s) visible", (x + 6, cy), 15, TEXT)
            cy += 24
        else:
            self.text("Engine reads this as:", (x + 6, cy), 13, MUTED)
            cy += 20
            for line in self.preview.description[:2]:
                cy = self.wrapped(line, x + 6, cy, width - 12, 15, TEXT, bold=True, lineGap=1)
        ignored = [chess.square_name(s) for s in self.draft.enemies if s not in self.visible]
        if ignored:
            self.wrapped(f"Not visible from your pieces, will be ignored: {', '.join(ignored)}", x + 6, cy + 2, width - 12, 13, BAD)
        y = card.bottom + 12

        if sightings:
            self.button((x, y, width - 130, 42), "Confirm  (Enter)", "sightings", "primary")
        else:
            self.button((x, y, width - 130, 42), "Opponent moved  (Enter)", "submit", "primary")
        self.button((x + width - 120, y, 120, 42), "Reset edits", "resetDraft")
        return y + 52

    def drawOver(self, x, y, width):
        won = self.engine.result == "win"
        self.text("You captured the king!" if won else "Your king was captured", (x, y), 22, GOOD if won else BAD, bold=True)
        y += 44
        self.button((x, y, width, 44), "New game  (Enter)", "newgame", "primary")
        return y + 60

    def drawHover(self, x, y):
        if self.engine is None or self.hover is None:
            return
        square = self.hover
        name = chess.square_name(square)
        if square in self.visible:
            self.text(f"{name}: visible", (x, y), 14, MUTED)
            return
        breakdown = sorted(self.engine.belief.squareBreakdown(square).items(), key=lambda item: -item[1])
        if not breakdown:
            self.text(f"{name}: fog, probably empty", (x, y), 14, MUTED)
            return
        parts = ", ".join(f"{round(p * 100)}% {chess.piece_name(t)}" for t, p in breakdown[:3] if p >= 0.005)
        self.text(f"{name}: fog, {parts or 'probably empty'}", (x, y), 14, TEXT)

    def drawFooter(self, x, width):
        y = HEIGHT - 100
        pygame.draw.line(self.screen, (52, 56, 66), (x - 6, y - 8), (x + width + 6, y - 8))
        third = (width - 12) // 3
        self.button((x, y, third, 30), "Heatmap (H)", ("toggle", "showHeat"), selected=self.showHeat, size=13)
        self.button((x + third + 6, y, third, 30), "Guesses (G)", ("toggle", "showGhosts"), selected=self.showGhosts, size=13)
        self.button((x + 2 * (third + 6), y, third, 30), "Flip (F)", ("toggle", "flipped"), selected=self.flipped, size=13)
        y += 38
        self.button((x, y, third, 30), "Undo (Ctrl+Z)", "undo", enabled=bool(self.undoStack) and self.phase != SETUP, size=13)
        label = "Click to confirm" if self.confirmNew else "New game"
        self.button((x + third + 6, y, third, 30), label, "newgame", enabled=self.phase != SETUP, size=13)
        if self.engine and self.engine.moveLog:
            # Numbered move pairs, as many of the latest as fit
            log = self.engine.moveLog
            offset = 0 if self.engine.color == chess.WHITE else 1     # Black's log starts with White's move
            entries = []
            for i, label in enumerate(log):
                ply = i + offset
                entries.append((f"{ply // 2 + 1}." if ply % 2 == 0 else "") + label)
            font, room, shown = self.font(12), third + 6, ""
            for entry in reversed(entries):
                attempt = (entry + " " + shown).strip()
                if font.size(attempt)[0] > room:
                    break
                shown = attempt
            self.text(shown, (x + 2 * (third + 6), y + 7), 12, MUTED)

    #############################
    #   Main loop
    #############################

    def run(self):
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()
                elif event.type == pygame.MOUSEMOTION:
                    self.mouse = event.pos
                    self.hover = self.squareAt(event.pos)
                elif event.type == pygame.KEYDOWN:
                    self.handleKey(event)
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    self.handleMouseDown(event)
                elif event.type == pygame.MOUSEBUTTONUP:
                    self.handleMouseUp(event)

            while self.results:
                generation, suggestions = self.results.pop(0)
                if generation == self.searchGen and self.phase == OURS:
                    self.suggestions = suggestions
                    self.highlight = 0
                    self.thinking = False

            self.buttons = []
            self.screen.fill(PANEL_BG)
            self.drawBoard()
            self.drawPanel()
            pygame.display.flip()
            self.clock.tick(config.FPS)


if __name__ == "__main__":
    App().run()
