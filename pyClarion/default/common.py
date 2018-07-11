"""This module defines commonly used constructs in the default implementation 
of Clarion.

Classes/functions defined here are used by at least two subsystems.
"""

from ..base import nodes
from ..base import activation
from ..base import action
from ..base import stats

import numpy as np


class TopDown(activation.TopDown):
    """A top-down (from a chunk to its microfeatures) activation channel.

    For details, see Section 3.2.2.3 para 2 of Sun (2016).

    References:
        Sun, R. (2016). Anatomy of the Mind. Oxford University Press.
    """

    def __init__(self, chunk : nodes.Chunk):
        """Set up the top-down activation flow from chunk to its microfeatures.

        kwargs:
            chunk : Source chunk for top-down activation.
        """
        
        self.chunk = chunk
        self.val_counts = self.count_values(self.chunk.microfeatures)

    def __call__(self, input_map : nodes.Node2Float) -> nodes.Node2Float:
        """Compute bottom-level activations given current chunk strength.

        Note: If the expected chunk is missing from the input, this channel 
        outputs an empty mapping.

        kwargs:
            input_map : A mapping from nodes (Chunks and/or Features) to 
            input activations.
        """

        try:
            strength = input_map[self.chunk]
        except KeyError:
            return dict()
        else:        
            activations = dict()
            for f in self.chunk.microfeatures:
                w_dim = self.chunk.dim2weight[f.dim()] 
                n_val = self.val_counts[f.dim()]
                activations[f] = strength * w_dim / n_val
            return activations

    @staticmethod
    def count_values(microfeatures: nodes.FeatureSet) -> nodes.Dim2Float:
        """Count the number of features in each dimension
        
        kwargs:
            microfeatures : A set of dv-pairs.
        """
        
        counts = dict()
        for f in microfeatures:
            try:
                counts[f.dim()] += 1
            except KeyError:
                counts[f.dim()] = 1
        return counts

class BottomUp(activation.BottomUp):
    """A top-down (from microfeatures to a chunk to its microfeatures) 
    activation channel.

    For details, see Section 3.2.2.3 para 3 of Sun (2016).

    References:
        Sun, R. (2016). Anatomy of the Mind. Oxford University Press.
    """

    def __init__(self, chunk : nodes.Chunk):
        """Set up the bottom-up activation flow to chunk from its microfeatures.

        kwargs:
            chunk : Target chunk for bottom-up activation.
        """
        
        self.chunk = chunk

    def __call__(self, input_map : nodes.Node2Float) -> nodes.Node2Float:
        """Compute chunk strength given current bottom-level activations.

        Note: If an expected (micro)feature is missing from the input, its 
        activation is assumed to be 0.

        kwargs:
            input_map : A mapping from nodes (Chunks and/or Features) to 
            input activations.
        """

        # For each dimension, pick the maximum available activation of the 
        # target chunk microfeatures in that dimension. 
        dim2activation = dict()
        for f in self.chunk.microfeatures:
            try:
                if dim2activation[f.dim()] < input_map[f]:
                    dim2activation[f.dim()] = input_map[f]
            except KeyError:
                # A KeyError may arise either because f.dim() is not in 
                # dim2activation, or because f is not in input_map. 
                # If the former is the case, add f.dim() to dim2activation, 
                # otherwise move on to the next microfeature.
                try: 
                    dim2activation[f.dim()] = input_map[f]
                except KeyError:
                    continue
        # Compute chunk strength based on dimensional activations.
        strength = 0.
        for dim in dim2activation:
            strength += self.chunk.dim2weight[dim] * dim2activation[dim]
        else:
            strength /= sum(self.chunk.dim2weight.values()) ** 1.1
        return {self.chunk: strength}

class Rule(activation.Rule):
    """An basic Clarion associative rule.

    Rules have the form:
        chunk_1 chunk_2 chunk_3 -> chunk_4
    Chunks in the left-hand side are condition chunks, the single chunk in the 
    right-hand side is the conclusion chunk. The strength of the conclusion 
    chunk resulting from rule application is a weighted sum of the strengths 
    of the condition chunks.

    This implementation is based on Chapter 3 of Sun (2016). 

    References:
    Sun, R. (2016). Anatomy of the Mind. Oxford University Press.
    """

    def __init__(
        self,
        chunk2weight : nodes.Chunk2Float,
        conclusion_chunk : nodes.Chunk
    ) -> None:
        """Initialize a Clarion associative rule.

        kwargs:
            chunk2weight : A mapping from condition chunks to their weights.
            conclusion_chunk : The conclusion chunk of the rule.
        """
        
        self.chunk2weight = chunk2weight
        self.conclusion_chunk = conclusion_chunk
    
    def __call__(self, input_map : nodes.Node2Float) -> nodes.Node2Float:
        """Return strength of conclusion chunk resulting from an application of 
        current associative rule.

        Note: If an expected chunk is missing from the input, its activation is 
        assumed to be 0.

        kwargs:
            input_map : A mapping from nodes (Chunks and/or Features) to 
            input activations.
        """
        
        strength = 0. 
        for chunk in self.chunk2weight:
            try:
                strength += input_map[chunk] * self.chunk2weight[chunk]
            except KeyError:
                continue
        return {self.conclusion_chunk: strength}

class MaxJunction(activation.ActivationJunction):
    """An activation junction returning max activations for all input nodes.
    """

    def __call__(self, *input_maps):
        """Return the maximum activation value for each input node.

        kwargs:
            input_maps : A set of mappings from chunks and/or (micro)features 
            to activations.
        """

        node_set = nodes.get_nodes(*input_maps)

        activations = dict()
        for node in node_set:
            for input_map in input_maps:
                try:
                    if activations[node] < input_map[node]:
                        activations[node] = input_map[node]
                except KeyError:
                    # Two cases: either node not in activations or node not in 
                    # input_map. Assume node not in activations, but in input 
                    # map, if this fails continue.
                    try:
                        activations[node] = input_map[node]
                    except KeyError:
                        continue

        return activations

class BoltzmannSelector(action.ChunkSelector):
    """Select a chunk according to a Boltzmann distribution.
    """

    def __init__(self, chunks: nodes.ChunkSet, temperature: float) -> None:
        """Initialize a BoltzmannSelector.

        kwargs:
            chunks : A set of (potentially) actionable chunks.
            temperature : Temperature of the Boltzmann distribution.
        """

        super().__init__(chunks)
        self.temperature = temperature

    def __call__(self, chunk2strength: nodes.Chunk2Float) -> nodes.ChunkSet:
        """Identify chunks that are currently actionable based on their 
        strengths according to a Boltzmann distribution.

        Note: If an expected input chunk is missing, it is assumed to have 
        activation 0.

        kwargs:
            chunk2strength : A mapping from chunks to their strengths.
        """

        terms = dict()
        divisor = 0.
        for chunk in self.chunks:
            try:
                terms[chunk] = np.exp(
                    chunk2strength[chunk] / self.temperature
                )
            except KeyError:
                # By assumption, chunk2strength[chunk] == 0. and exp(0. / t) 
                # is 1.0.
                terms[chunk] = 1.0
            divisor += terms[chunk]

        chunk_list = list(self.chunks)
        probabilities = [terms[chunk] / divisor for chunk in chunk_list]
        choice = np.random.choice(chunk_list, p=probabilities)

        return {choice}

class BLA(stats.Stat):
    """Keeps track of base-level activations (BLAs).

    Implemented according to Sun (2016) Chapter 3. See Section 3.2.1.3 (p. 62)
    and also Section 3.2.2.2 (p. 77).

    Warning: This class has no knowledge of the chunks, rules and other 
    constructs associated with the statistics it tracks.

    References:
        Sun, R. (2016). Anatomy of the Mind. Oxford University Press.
    """

    def __init__(
        self,  
        initial_activation : float = 0., 
        amplitude : float = 2., 
        decay_rate : float = .5, 
        density: float = 0.
    ) -> None:
        """Initialize a BLA instance.

        Warning: By default, a timestamp is not added at initialization. If a 
        timestamp is required at creation time, call self.add_timestamp.
        """
        
        self.initial_activation = initial_activation
        self.amplitude = amplitude
        self.decay_rate = decay_rate
        self.density = density

        self.timestamps = []

    def update(self, current_time : float) -> None:
        """Record current time as an instance of use and/or activation for 
        associated construct.
        """

        self.timestamps.append(current_time)

    def compute_bla(self, current_time : float) -> float:
        """Compute the current BLA.

        Warning: Will result in division by zero if called immediately after 
        update.
        """

        summation_terms = [
            (current_time - t) ** (- self.decay_rate) 
            for t in self.timestamps
        ]
        bla = (
            self.initial_activation + (self.amplitude  *  sum(summation_terms))
        )
        return bla

    def below_density(self, current_time : float) -> bool:
        """Return true if BLA is below density.
        """

        return self.compute_bla(current_time) < self.density

class MatchStatistics(stats.Stat):
    """Tracks positive and negative match statistics.

    Implemented according to Sun (2016) Chapter 3. See Section 3.3.2.1 (p. 90).

    Warning: This class is not responsible for testing positive or negative 
    match criteria, and has no knowledge of the chunks and actions associated 
    with the statistics it tracks.  

    References:
        Sun, R. (2016). Anatomy of the Mind. Oxford University Press.
    """

    def __init__(self) -> None:
        """Initialize tracking for a set of match statistics.
        """

        self.positive_matches = 0.
        self.negative_matches = 0.

    def update(self, positive_match : bool) -> None:
        """Update current match statistics.

        kwargs:
            positive_match : True if the positivity criterion is satisfied, 
            false otherwise.
        """

        if positive_match:
            self.positive_matches += 1.
        else: 
            self.negative_matches += 1.

    def discount(self, multiplier : float) -> None:
        """Discount match statistics.
        """
        
        self.positive_matches *= multiplier
        self.negative_matches *= multiplier