# Copyright (c) 2013 The SAYCBridge Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from .model import *
from .preconditions import *
from .constraints import *
from third_party import enum
from core.call import Call
from third_party.memoized import memoized
from itertools import chain
from .orderings import PartialOrdering


categories = enum.Enum(
    "Relay",
    "FeatureAsking",
    "NoTrump",
)


class TransferTo(object):
    def __init__(self, suit):
        self.suit = suit


class Rule(object):
    # FIXME: Consider splitting call_preconditions out from preconditions
    # for preconditions which only operate on the call?
    preconditions = []
    category = None # Intra-bid priority
    requires_planning = False

    call_name = None # call_name = '1C' -> preconditons = [CallName('1C')]
    call_names = None # call_names = ['1C', '1D'] -> preconditons = [CallNames('1C', '1D')]

    constraints = {}
    shared_constraints = []
    annotations = []
    conditional_priorities = []
    priority = None

    def __init__(self):
        assert self.priority or self.constraints, "" + self.name() + " is missing priority"
        assert not self.conditional_priorities or not self.constraints
        # conditional_priorities only works with a single call_name.
        assert not self.conditional_priorities or self.call_name

    def name(self):
        return self.__class__.__name__

    def __repr__(self):
        return "%s()" % self.name()

    def _fits_preconditions(self, history, call):
        for precondition in self.preconditions:
            if not precondition.fits(history, call):
                return False
        return True

    def _possible_calls_over(self, history):
        # If this Rule has explicit call restrictions, we only need to consider those.
        # FIXME: We should probably standardize this on some sort of call_preconditions instead.        
        if self.call_name:
            return [Call.from_string(self.call_name)]
        elif self.call_names:
            return map(Call.from_string, self.call_names)
        elif self.constraints:
            return map(Call.from_string, self.constraints.keys())
        # Otherwise we need to run all possible calls through the preconditions.
        return CallExplorer().possible_calls_over(history.call_history)

    def calls_over(self, history):
        for call in self._possible_calls_over(history):
            if self._fits_preconditions(history, call):
                yield call

    def possible_priorities_and_conditions_for_call(self, call):
        # conditional_priorities only work for a single call_name
        for condition, priority in self.conditional_priorities:
            yield priority, condition

        _, priority = self._per_call_constraints_and_priority(call)
        assert priority
        yield priority, NO_CONSTRAINTS

    @memoized
    def priority_for_call_and_hand(self, solver, history, call, hand):
        if not is_possible(solver, self.constraints_expr_for_call(history, call)):
            return None

        for condition, priority in self.conditional_priorities:
            if is_possible(solver, condition):
                return priority

        _, priority = self._per_call_constraints_and_priority(call)
        if priority:
            return priority

        return self.priority

    def _exprs_from_constraints(self, constraints, history, call):
        if not constraints:
            return [NO_CONSTRAINTS]

        if isinstance(constraints, Constraint):
            return [constraints.expr(history, call)]

        if isinstance(constraints, z3.ExprRef):
            return [constraints]

        return chain.from_iterable([self._exprs_from_constraints(constraint, history, call) for constraint in constraints])

    # constraints accepts various forms including:
    # constraints = { '1H': hearts > 5 }
    # constraints = { '1H': (hearts > 5, priority) }

    # FIXME: Should we split this into two methods? on for priority and one for constraints?
    def _per_call_constraints_and_priority(self, call):
        constraints_tuple = self.constraints.get(call.name)
        if not constraints_tuple:
            return None, self.priority

        try:
            if isinstance(list(constraints_tuple)[-1], enum.EnumValue):
                assert len(constraints_tuple) == 2
                return constraints_tuple
        except TypeError:
            return constraints_tuple, self.priority

    def constraints_expr_for_call(self, history, call):
        exprs = []
        per_call_constraints, _ = self._per_call_constraints_and_priority(call)
        if per_call_constraints:
            exprs.extend(self._exprs_from_constraints(per_call_constraints, history, call))
        exprs.extend(self._exprs_from_constraints(self.shared_constraints, history, call))
        return z3.And(exprs)


opening_priorities = enum.Enum(
    "StrongTwoClubs",
    "NoTrumpOpening",
    "LongestMajor",
    "HigherMajor",
    "LowerMajor",
    "LongestMinor",
    "HigherMinor",
    "LowerMinor",
)


class Opening(Rule):
    annotations = [annotations.Opening]
    preconditions = [NoOpening()]


class OneClubOpening(Opening):
    call_name = '1C'
    shared_constraints = [rule_of_twenty, clubs >= 3]
    conditional_priorities = [
        (z3.Or(clubs > diamonds, z3.And(clubs == 3, diamonds == 3)), opening_priorities.LongestMinor),
    ]
    priority = opening_priorities.LowerMinor


class OneDiamondOpening(Opening):
    call_name = '1D'
    shared_constraints = [rule_of_twenty, diamonds >= 3]
    conditional_priorities = [
        (diamonds > clubs, opening_priorities.LongestMinor),
    ]
    priority = opening_priorities.HigherMinor


class OneHeartOpening(Opening):
    call_name = '1H'
    shared_constraints = [rule_of_twenty, hearts >= 5]
    conditional_priorities = [
        (hearts > spades, opening_priorities.LongestMajor),
    ]
    priority = opening_priorities.LowerMajor


class OneSpadeOpening(Opening):
    call_name = '1S'
    shared_constraints = [rule_of_twenty, spades >= 5]
    conditional_priorities = [
        (spades > hearts, opening_priorities.LongestMajor),
    ]
    priority = opening_priorities.HigherMajor


class NoTrumpOpening(Opening):
    annotations = Opening.annotations + [annotations.NoTrumpSystemsOn]
    constraints = {
        '1N': z3.And(points >= 15, points <= 17, balanced),
        '2N': z3.And(points >= 20, points <= 21, balanced)
    }
    priority = opening_priorities.NoTrumpOpening


# class OneNoTrumpOpening(Opening):
#     call_name = '1N'
#     shared_constraints = 


# class TwoNoTrumpOpening(Opening):
#     annotations = Opening.annotations + [annotations.NoTrumpSystemsOn]
#     call_name = '2N'
#     shared_constraints = [points >= 20, points <= 21, balanced]
#     priority = opening_priorities.NoTrumpOpening


class StrongTwoClubs(Opening):
    call_name = '2C'
    shared_constraints = points >= 22  # FIXME: Should support "or 9+ winners"
    priority = opening_priorities.StrongTwoClubs


response_priorities = enum.Enum(
    "MajorLimitRaise",
    "MajorMinimumRaise",
    "LongestNewMajor",
    "OneSpadeWithFiveResponse",
    "OneHeartWithFiveResponse",
    "OneDiamondResponse",
    "OneHeartWithFourResponse",
    "OneSpadeWithFourResponse",
    "TwoHeartNewSuitResponse",
    "TwoSpadeNewSuitResponse",
    "TwoClubNewSuitResponse",
    "TwoDiamondNewSuitResponse",
    "OneNotrumpResponse",
)


class Response(Rule):
    preconditions = [LastBidHasAnnotation(positions.Partner, annotations.Opening)]


class OneDiamondResponse(Response):
    call_name = '1D'
    shared_constraints = [points >= 6, diamonds >= 4]
    priority = response_priorities.OneDiamondResponse


class OneHeartResponse(Response):
    call_name = '1H'
    shared_constraints = [points >= 6, hearts >= 4]
    conditional_priorities = [
        (z3.And(hearts >= 5, hearts > spades), response_priorities.LongestNewMajor),
        (hearts >= 5, response_priorities.OneHeartWithFiveResponse),
    ]
    priority = response_priorities.OneHeartWithFourResponse


class OneSpadeResponse(Response):
    call_name = '1S'
    shared_constraints = [points >= 6, spades >= 4]
    conditional_priorities = [
        (spades >= 5, response_priorities.OneSpadeWithFiveResponse)
    ]
    priority = response_priorities.OneSpadeWithFourResponse


class OneNotrumpResponse(Response):
    call_name = '1N'
    shared_constraints = points >= 6
    priority = response_priorities.OneNotrumpResponse


class RaiseResponse(Response):
    preconditions = Response.preconditions + [RaiseOfPartnersLastSuit(), LastBidHasAnnotation(positions.Partner, annotations.Opening)]


class MajorMinimumRaise(RaiseResponse):
    call_names = ['2H', '2S']
    shared_constraints = [MinimumCombinedLength(8), points >= 6]
    priority = response_priorities.MajorMinimumRaise


class MajorLimitRaise(RaiseResponse):
    call_names = ['3H', '3S']
    shared_constraints = [MinimumCombinedLength(8), points >= 10]
    priority = response_priorities.MajorLimitRaise


# We should bid longer suits when possible, up the line for 4 cards.
# we don't currently bid 2D over 2C when we have longer diamonds.

class NewSuitAtTheTwoLevel(Response):
    preconditions = Response.preconditions + [UnbidSuit(), NotJumpFromLastContract()]
    constraints = {
        '2C' : (clubs >= 4, response_priorities.TwoClubNewSuitResponse),
        '2D' : (diamonds >= 4, response_priorities.TwoDiamondNewSuitResponse),
        '2H' : (hearts >= 5, response_priorities.TwoHeartNewSuitResponse),
        '2S' : (spades >= 5, response_priorities.TwoSpadeNewSuitResponse),
    }
    shared_constraints = points >= 10


nt_response_priorities = enum.Enum(
    "NoTrumpJumpRaise",
    "NoTrumpMinimumRaise",
    "JacobyTransferToLongerMajor",
    "JacobyTransferToSpadesWithGameForcingValues",
    "JacobyTransferToHeartsWithGameForcingValues",
    "JacobyTransferToHearts",
    "JacobyTransferToSpades",
    "Stayman",
    "ClubBust",
)


class NoTrumpResponse(Response):
    category = categories.NoTrump
    preconditions = Response.preconditions + [
        LastBidHasAnnotation(positions.Partner, annotations.Opening),
        LastBidHasAnnotation(positions.Partner, annotations.NoTrumpSystemsOn),
    ]


class BasicStayman(NoTrumpResponse):
    annotations = Response.annotations + [annotations.Artificial, annotations.Stayman]
    priority = nt_response_priorities.Stayman
    shared_constraints = [z3.Or(hearts >= 4, spades >= 4)]


class Stayman(BasicStayman):
    preconditions = BasicStayman.preconditions + [NotJumpFromPartnerLastBid()]
    constraints = {
        '2C': MinimumCombinedPoints(23),
        '3C': MinimumCombinedPoints(25),
    }


class StolenTwoClubStayman(BasicStayman):
    preconditions = BasicStayman.preconditions + [LastBidWas(positions.RHO, '2C')]
    constraints = { 'X': MinimumCombinedPoints(23) }


class StolenThreeClubStayman(BasicStayman):
    preconditions = BasicStayman.preconditions + [LastBidWas(positions.RHO, '3C')]
    constraints = { 'X': MinimumCombinedPoints(25) }


class JacobyTransfer(NoTrumpResponse):
    annotations = NoTrumpResponse.annotations + [annotations.Artificial, TransferTo(suit.HEARTS)]


class JacobyTransferToHearts(JacobyTransfer):
    call_name = '2D'
    shared_constraints = hearts >= 5
    conditional_priorities = [
        (hearts > spades, nt_response_priorities.JacobyTransferToLongerMajor),
        (z3.And(hearts == spades, points >= 10), nt_response_priorities.JacobyTransferToHeartsWithGameForcingValues),
    ]
    priority = nt_response_priorities.JacobyTransferToHearts


class JacobyTransferToSpades(JacobyTransfer):
    call_name = '2H'
    shared_constraints = spades >= 5
    conditional_priorities = [
        (spades > hearts, nt_response_priorities.JacobyTransferToLongerMajor),
        (z3.And(hearts == spades, points >= 10), nt_response_priorities.JacobyTransferToSpadesWithGameForcingValues),
    ]
    priority = nt_response_priorities.JacobyTransferToSpades


# FIXME: We don't support multiple call names...
# class AcceptTransfer(Rule):
#     category = categories.Relay
#     preconditions = Rule.preconditions + [
#         LastBidHasAnnotationOfClass(positions.Partner, TransferTo),
#         NotJumpFromPartnerLastBid(),
#     ]


stayman_response_priorities = enum.Enum(
    "HeartStaymanResponse",
    "SpadeStaymanResponse",
    "DiamondStaymanResponse",
    "PassStaymanResponse",
)


class StaymanResponse(Rule):
    preconditions = Rule.preconditions + [LastBidHasAnnotation(positions.Partner, annotations.Stayman)]


class NaturalStaymanResponse(StaymanResponse):
    preconditions = StaymanResponse.preconditions + [NotJumpFromPartnerLastBid()]
    constraints = {
        '2H': (hearts >= 4, stayman_response_priorities.HeartStaymanResponse),
        '2S': (spades >= 4, stayman_response_priorities.SpadeStaymanResponse),
        '3H': (hearts >= 4, stayman_response_priorities.HeartStaymanResponse),
        '3S': (spades >= 4, stayman_response_priorities.SpadeStaymanResponse),
    }


class PassStaymanResponse(StaymanResponse):
    call_name = 'P'
    shared_constraints = NO_CONSTRAINTS
    priority = stayman_response_priorities.PassStaymanResponse


class DiamondStaymanResponse(StaymanResponse):
    preconditions = StaymanResponse.preconditions + [NotJumpFromPartnerLastBid()]
    constraints = {
        '2D': NO_CONSTRAINTS,
        '3D': NO_CONSTRAINTS,
    }
    priority = stayman_response_priorities.DiamondStaymanResponse
    annotations = StaymanResponse.annotations + [annotations.Artificial]


# FIXME: Need "Stolen" variants for 3-level.
class StolenHeartStaymanResponse(StaymanResponse):
    constraints = { 'X': hearts >= 4 }
    preconditions = StaymanResponse.preconditions + [LastBidWas(positions.RHO, '2H')]
    priority = stayman_response_priorities.HeartStaymanResponse


class StolenSpadeStaymanResponse(StaymanResponse):
    constraints = { 'X': spades >= 4 }
    preconditions = StaymanResponse.preconditions + [LastBidWas(positions.RHO, '2S')]
    priority = stayman_response_priorities.SpadeStaymanResponse


overcall_priorities = enum.Enum(
    # FIXME: This needs the prefer the longer suit pattern.
    "DirectOvercall",
    "FourLevelPremptive",
    "ThreeLevelPremptive",
    "TwoLevelPremptive",
)


class DirectOvercall(Rule):
    preconditions = Rule.preconditions + [LastBidHasAnnotation(positions.RHO, annotations.Opening)]
    priority = overcall_priorities.DirectOvercall


class OneLevelOvercall(DirectOvercall):
    call_names = ['1D', '1H', '1S']
    shared_constraints = [MinLength(5), points >= 8]


preempt_priorities = enum.Enum(
    "FourLevelPremptive",
    "ThreeLevelPremptive",
    "TwoLevelPremptive",
)


class TwoLevelPremptiveOpen(Opening):
    call_names = ['2D', '2H', '2S']
    shared_constraints = [MinLength(6), ThreeOfTheTopFive(), points >= 5]
    priority = preempt_priorities.TwoLevelPremptive


class ThreeLevelPremptiveOpen(Opening):
    call_names = ['3C', '3D', '3H', '3S']
    shared_constraints = [MinLength(7), ThreeOfTheTopFive(), points >= 5]
    priority = preempt_priorities.ThreeLevelPremptive


class FourLevelPremptiveOpen(Opening):
    call_names = ['4C', '4D', '4H', '4S']
    shared_constraints = [MinLength(8), ThreeOfTheTopFive(), points >= 5]
    priority = preempt_priorities.FourLevelPremptive


# FIXME: Should we use conditional priorities instead of upper bounding the points?
class TwoLevelPremptiveOvercall(DirectOvercall):
    preconditions = DirectOvercall.preconditions + [JumpFromLastContract()]
    call_names = ['2C', '2D', '2H', '2S']
    shared_constraints = [MinLength(6), ThreeOfTheTopFive(), points >= 5]
    priority = overcall_priorities.TwoLevelPremptive


class ThreeLevelPremptiveOvercall(DirectOvercall):
    preconditions = DirectOvercall.preconditions + [JumpFromLastContract()]
    call_names = ['3C', '3D', '3H', '3S']
    shared_constraints = [MinLength(7), ThreeOfTheTopFive(), points >= 5]
    priority = overcall_priorities.ThreeLevelPremptive


class FourLevelPremptiveOvercall(DirectOvercall):
    preconditions = DirectOvercall.preconditions + [JumpFromLastContract()]
    call_names = ['4C', '4D', '4H', '4S']
    shared_constraints = [MinLength(8), ThreeOfTheTopFive(), points >= 5]
    priority = overcall_priorities.FourLevelPremptive


feature_asking_priorites = enum.Enum(
    "Gerber",
    "Blackwood",
)


class Gerber(Rule):
    category = categories.FeatureAsking
    requires_planning = True
    shared_constraints = NO_CONSTRAINTS
    annotations = [annotations.Gerber]
    priority = feature_asking_priorites.Gerber


class GerberForAces(Gerber):
    call_name = '4C'
    preconditions = Gerber.preconditions + [
        LastBidHasStrain(positions.Partner, suit.NOTRUMP),
        InvertedPrecondition(LastBidHasAnnotation(positions.Partner, annotations.Artificial))
    ]


class GerberForKings(Gerber):
    call_name = '5C'
    preconditions = Gerber.preconditions + [
        LastBidHasAnnotation(positions.Me, annotations.Gerber)
    ]


class ResponseToGerber(Rule):
    category = categories.Relay
    preconditions = Rule.preconditions + [
        LastBidHasAnnotation(positions.Partner, annotations.Gerber),
        NotJumpFromPartnerLastBid(),
    ]
    constraints = {
        '4D': z3.Or(number_of_aces == 0, number_of_aces == 4),
        '4H': number_of_aces == 1,
        '4S': number_of_aces == 2,
        '4N': number_of_aces == 3,
        '5D': z3.Or(number_of_kings == 0, number_of_kings == 4),
        '5H': number_of_kings == 1,
        '5S': number_of_kings == 2,
        '5N': number_of_kings == 3,
    }
    priority = feature_asking_priorites.Gerber
    annotations = [annotations.Artificial]


# Blackwood is done, just needs JumpOrHaveFit() and some testing.
# class Blackwood(Rule):
#     category = categories.FeatureAsking
#     requires_planning = True
#     shared_constraints = NO_CONSTRAINTS
#     annotations = [annotations.Blackwood]
#     priority = feature_asking_priorites.Blackwood


# class BlackwoodForAces(Blackwood):
#     call_name = '4N'
#     preconditions = Blackwood.preconditions + [
#         InvertedPrecondition(LastBidHasStrain(positions.Partner, suit.NOTRUMP)),
#         InvertedPrecondition(LastBidHasAnnotation(positions.Partner, annotations.Artificial)),
#         JumpOrHaveFit()
#     ]


# class BlackwoodForKings(Blackwood):
#     call_name = '5N'
#     preconditions = Blackwood.preconditions + [
#         LastBidHasAnnotation(positions.Me, annotations.Blackwood)
#     ]


# class ResponseToBlackwood(Rule):
#     category = categories.Relay
#     preconditions = Rule.preconditions + [
#         LastBidHasAnnotation(positions.Partner, annotations.Blackwood),
#         NotJumpFromPartnerLastBid(),
#     ]
#     constraints = {
#         '4C': z3.Or(number_of_aces == 0, number_of_aces == 4),
#         '4D': number_of_aces == 1,
#         '4H': number_of_aces == 2,
#         '4S': number_of_aces == 3,
#         '5C': z3.Or(number_of_kings == 0, number_of_kings == 4),
#         '5D': number_of_kings == 1,
#         '5H': number_of_kings == 2,
#         '5S': number_of_kings == 3,
#     }
#     priority = feature_asking_priorites.Blackwood
#     annotations = [annotations.Artificial]


# FIXME: This is wrong as soon as we try to support more than one system.
def _get_subclasses(base_class):
    subclasses = base_class.__subclasses__()
    for subclass in list(subclasses):
        subclasses.extend(_get_subclasses(subclass))
    return subclasses

def _concrete_rule_classes():
    return filter(lambda rule: not rule.__subclasses__(), _get_subclasses(Rule))


class StandardAmericanYellowCard(object):
    # Rule ordering does not matter.  We could have python crawl the files to generate this list instead.
    rules = [rule() for rule in _concrete_rule_classes()]
    priority_ordering = PartialOrdering()

    priority_ordering.make_less_than(response_priorities, nt_response_priorities)
    priority_ordering.make_less_than(preempt_priorities, opening_priorities)