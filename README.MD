To run an example game, install the following dependencies, and run start.py

pip install chess pygame




A Fog of War Chess AI that can play based on Belief States

Fog of War Chess is a vairent of the classical board game chess. Also commonly cknown as Dark Chess, Hidden Chess, or similar to Kriegspiel. The piece moves and goal are identical to standard chess. The variation in Fog of War Chess is the introduction of a fog of war cloud, such that the player can only see the board where their own pieces can move to. Where chess is normally a fully observable statespace, fog of war creates a board of uncertainty, where players rely on probability to gain an advantage.

This is Version 2 of Fog of War since the first was kind of a mess




This Fog of War engine, utilizes Sunfish to evaluate positions. Sunfish is a lightweight chess engine that can beat majority of human players. Compared to more advanced supercomputers, Sunfish does not have a set knowledge of winning opening positions (though proper play tends to resemble known opening theory anyways). Sunfish was chosen over a more popular and stronger option like Stockfish, becuase more powerful engines tend to require massive amounts more storage space than sunfish, making them non deployable to a github repository.

Standard chess engines are not programmed to handle uncertainty, as chess is a game with complete information at all times. A game that incorperates uncertainty would be something like Poker which relies more on probability and social reads for computers. Fog of war chess in similar because a player cannot see squares that they do not control. This gap of what is observed and what is the true board state, is what my chess engine attempts to fix. A belief state is created by a computer and updates after an observation, and in this case a belief state is a model of a chessboard, with the pieces placed on squares where the computer believes that they are. 

One primary challenge of creating an AI for chess, is the branching factor (~35) which means that searching a state space after just four moves becomes infeasible. Methods of searching the state space do not search the entire tree, but rather sections of it in order to find the best move. Additionally, fog of war adds another layer of complexity over standard chess. In a naive program, the enemy pieces could be in any position in the board, increasing the amount of possible states to search. 

The first method I attempted to alleviate partial observability was to use a  particle filter, where each particle was a possible state of the chess board. Then a random particle is chosen from a list for a belief state, and is then evaluated by sunfish for the computer's best move. This was very naive, and created nearly random positions with no regard to standard play or piece placement. Ex. a king could end up in the middle of the board and be missing half of it's color pieces. This was incredibly reudementary and resulted in the computer going for phantom pieces that didn't exist in its believed position. Part of a particle filter is an observation step. This was implemented in conjunction with the particle filter to remove particles that didnt align with an observation. For example, if the computer believes that a pawn is on the square e4, but then the computer moves a piece such that it gains view of the e4 square, if the computer then observed that there is or isnt a pawn on e4, it will update its belief state by either removing each particle that doesnt align with what it just saw. Then it will replenish any particles lost so that it always maintains some number of particles in the filter. 

An improvement done to the particle filter was adding a transitional model. This is possible because we know that each chess game starts with the exact same position. Using this knowledge, we can make each particle significantly more accurate, by only allowing each particle to make one legal move per computer turn. This significantly reduces the number of nonsensical positions and allows the AI to play more accurately. This might be able to beat a lower rated beginner at chess, but more in part due to the beginner's faults than to the algortihm's strength. The largest issue with a particle filter in this context is particle deprivation, or the scenerio where the state space becomes so unpredictable and random, that eventually none of the particles algin with what the actual game look like. A particle filter excels at tracking a single target, but asking it to track an entire board leads to mass elimination of particles at each step. This is not sustainable for longer games. 

An idea that I had was what if each piece had its own particle filter, then you could track each piece and create the most probable board for the belief state. This lends itself more to what a Discrete Bayes Filter is designed to handle. A particle filters requires frequent updates of a pieces position, in fog of war chess this may not be feasible or frequent enough to make a good estimation, and unless it is an exact match it discrards too many partikcles. A Bayes Filter creates a grid of probabilitie based on each piece's known transitions. For example, if a bishop is on its starting square, then because it moves diagonally, we know that those squares along the diagonal have a higher probability of having a bishop than the squares not along that line. Once we make an observation of the bishop, even if it retreats into the fog, we have a better idea of where the bishop could have gone.

Additionally, a core part of the Bayes Filter is the probability of an observation being true. However, in our case observations are always true, so the proability of an observation being correct is 1, or in the case that an observation is disproved by the state, then P(observation|state) = 0
 

Histogram Filter (V3)

The belief state (beliefState.py) is now a Histogram filter, a discrete Bayes filter. Every enemy piece gets its own 64 square grid of probabilities, and the game always starts from the same known position so every grid starts out certain. Tracking each piece separately instead of one grid per piece type keeps information like "this pawn is on the e-file" or "this bishop lives on dark squares".

Each enemy move runs two steps:
- Prediction: probability flows from each square to the squares that piece could move to. Which piece moved is weighted by how many moves it has, by piece type (kings move less often than knights), and by whether the move would threaten our pieces or king, since players rarely move at random. Squares that probably hold another piece only partly block a sliding piece (it gets past with probability 1 - occupancy), so a guess never rules a square out completely.
- Observation: a visible empty square drops to 0 for every piece, and a visible enemy piece is matched to the tracked piece that most likely is that piece (data association), which then becomes certain. A piece seen where no tracked piece could be means a pawn promoted, or the filter lost track of something, and it recovers by starting that piece's grid over.

The engine (engine.py) draws several complete boards from the belief state: the most likely board plus random samples. Sunfish suggests a move on each board, then every shortlisted move is scored on every board and the scores are averaged, so a move only wins if it is good across the positions the enemy could really be in. The histogram also gives the probability that a hidden piece can capture our king after each move, and that risk is taken off the move's score.

In testing (engine.py driven by only what it can see) the engine won 8 out of 8 games against Sunfish playing with the same fog and no belief state, with equal thinking time.
