import pygame, sys, random, chess, platform
from pygame.locals import *


BOARDSIZE = 800 # How large the board appears on screen. I recommend using multiples of 200 for cleanest look
FPS = 60

#Colors of board squares in RGB format
SQUARECOLOR_LIGHT = (255, 255, 255) 
SQUARECOLOR_DARK = (118, 150, 86)


PLAYER_COLOR = chess.WHITE # Set to chess.BLACK for black pieces, chess.WHITE for white pieces

#Around 6 depth and 2 seconds sunfish gets really strong
SUNFISH_DEPTH = 2 #Depth of how many moves Sunfish will look ahead. Higher means stronger
SUNFISH_TIME = 1.5 #Similarly, how long can Sufish think for ,longer is stronger

