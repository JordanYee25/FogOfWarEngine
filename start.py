import pygame, sys, random, chess, platform
from gameState import gameState
from pygame.locals import *
import config , game

newGame = game.game()

while True:

    gamestep = newGame.step()

    #PGN updated/prints per move
    if gamestep == "move":
        #If you want to access PGN once per turn
        PGN = newGame.PGN
        print("Game PGN: ", PGN)
    elif gamestep == "gameover": 
        newGame.waitForClose() # Result screen stays up until a click or key press
        break

    #Otherwise if you want PGN at every frame... for some reason:
    # PGN = newGame.PGN
    # print("Game PGN: ", PGN)

    # if gamestep == "gameover": 
    #     break

print()
if newGame.gameState.board.result() == "1-0":
    print("Game Over - White wins!")
elif newGame.gameState.board.result() == "0-1":
    print("Game Over - Black wins!")
else:
    print("Game Over - Draw!")

#Final PGN
FinalPGN = newGame.PGN
print("Final Game PGN: ", FinalPGN)