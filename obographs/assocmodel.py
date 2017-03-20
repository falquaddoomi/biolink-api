"""Simple association model

The core class here is AssociationSet, a holder for a set of
associations between entities such as genes and ontology
classes. AssociationSets can also be throught of as subsuming
traditional 'gene sets'

The model is deliberately simple, and does not seek to represent
metadata about the association - it is assumed that this is handled
upstream. See the assoc_factory module for details - this allows the
client to create an association set based on various criteria such as
taxa of interest or evidence criteria.

"""
import logging
import scipy.stats # TODO - move
import scipy as sp # TODO - move

class UnknownSubjectException():
    pass

class AssociationSet():
    """An object that represents a collection of associations

    NOTE: the intention is that this class can be subclassed to provide
    either high-efficiency implementations, or implementations backed by services or external stores.
    The default implementation is in-memory.

    """

    def __init__(self, ontology=None, association_map={}, meta=None):
        """
        NOTE: in general you do not need to call this yourself. See assoc_factory

        initializes an association set, which minimally consists of:

         - an ontology (e.g. GO, HP)
         - a map between subjects (e.g genes) and sets/lists of term IDs

        """
        self.ontology = ontology
        self.association_map = association_map
        self.subject_to_inferred_map = {}
        self.meta = meta  # TODO
        self.strict = False
        self.index()
        logging.info("Created {}".format(self))

    def index(self):
        """
        Creates indexes based on inferred terms.

        You do not need to call this yourself; called on initialization
        """
        self.subjects = list(self.association_map.keys())
        logging.info("Indexing {} items".format(len(self.subjects)))
        n = 0
        for (subj,terms) in self.association_map.items():
            ancs = self.termset_ancestors(terms)
            self.subject_to_inferred_map[subj] = ancs
            n = n+1
            if n<5:
                logging.info(" Indexed: {} -> {}".format(subj, ancs))
            elif n == 6:
                logging.info("....")

    def inferred_types(self, subj):
        """
        Returns: set of reflexive inferred types for a subject.

        E.g. if a gene is directly associated with terms A and B, and these terms have ancestors C, D and E
        then the set returned will be {A,B,C,D,E}
        
        Arguments
        ---------

          subj - ID string

        Returns: set of class IDs

        """
        if subj in self.subject_to_inferred_map:
            return self.subject_to_inferred_map[subj]
        if self.strict:
            raise UnknownSubjectException(subj)
        else:
            return set([])
        
    def termset_ancestors(self, terms):
        """
        reflexive ancestors

        Arguments
        ---------

          terms - a set or list of class IDs

        Returns: set of class IDs
        """
        ancs = set()
        for term in terms:
            ancs = ancs.union(self.ontology.ancestors(term))
        return ancs.union(set(terms))
            
    def query(self, terms=[], negated_terms=[]):
        """
        Basic boolean query, using inference
        """
        termset = set(terms)
        negated_termset = set(negated_terms)
        matches = []
        n_terms = len(termset)
        for subj in self.subjects:
            if len(termset.intersection(self.inferred_types(subj))) == n_terms:
                if len(negated_termset.intersection(self.inferred_types(subj))) == 0:
                    matches.append(subj)
        return matches

    def query_intersections(self, x_terms=[], y_terms=[]):
        """
        Query for intersections of terms in two lists

        Return a list of intersection result objects
        """
        xset = set(x_terms)
        yset = set(y_terms)
        zset = xset.union(yset)

        # first built map of gene->termClosure.
        # this could be calculated ahead of time for all g,
        # but this may be space-expensive. TODO: benchmark
        gmap={}
        for z in zset:
            gmap[z] = []
        for subj in self.subjects:
            ancs = self.inferred_types(subj)
            for a in ancs.intersection(zset):
                gmap[a].append(subj)
        for z in zset:
            gmap[z] = set(gmap[z])
        ilist = []
        for x in x_terms:
            for y in x_terms:
                if x<y:
                    shared = gmap[x].intersection(gmap[y])
                    ilist.append({'x':x,'y':y,'shared':shared, 'c':len(shared)})
        return ilist

    def enrichment_test(self, subjects=[], background=None, threshold=0.05, labels=False, direction='greater'):
        """
        Performs term enrichment analysis

        Arguments
        ---------

        subjects: string list

            Sample set. Typically a gene ID list. These are assumed to have associations

        background: string list

            Background set. If not set, uses full set of known subject IDs in the association set

        threshold: float

            p values above this are filtered out

        labels: boolean

            if true, labels for enriched classes are included in result objects

        direction: 'greater', 'less' or 'two-sided'

            default is greater - i.e. enrichment test. Use 'less' for depletion test.

        """
        subjects=set(subjects)
        bg_count = {}
        sample_count = {}
        hypotheses = set()
        sample_size = len(subjects)
        for s in subjects:
            hypotheses.update(self.inferred_types(s))
        logging.info("Hypotheses: {}".format(hypotheses))
        
        # get background counts
        # TODO: consider doing this ahead of time
        if background is None:
            background = set(self.subjects)
        else:
            background = set(background)

        # ensure background includes all subjects
        background.update(subjects)
        
        bg_size = len(background)
        
        for c in hypotheses:
            bg_count[c] = 0
            sample_count[c] = 0
        for s in background:
            ancs = self.inferred_types(s)
            for a in ancs.intersection(hypotheses):
                bg_count[a] = bg_count[a]+1
        for s in subjects:
            for a in self.inferred_types(s):
                sample_count[a] = sample_count[a]+1

        hypotheses = [x for x in hypotheses if bg_count[x] > 1]
        logging.info("Filtered hypotheses: {}".format(hypotheses))
        num_hypotheses = len(hypotheses)
                
        results = []
        for cls in hypotheses:
            
            # https://en.wikipedia.org/wiki/Fisher's_exact_test
            #
            #              Cls  NotCls    RowTotal
            #              ---  ------    ---
            # study/sample [a,      b]    sample_size
            # rest of ref  [c,      d]    bg_size - sample_size
            #              ---     ---
            #              nCls  nNotCls

            a = sample_count[cls]
            b = sample_size - a
            c = bg_count[cls] - a
            d = (bg_size - bg_count[cls]) - b
            logging.debug("ABCD="+str((cls,a,b,c,d,sample_size)))
            _, p_uncorrected = sp.stats.fisher_exact( [[a, b], [c, d]], direction)
            p = p_uncorrected * num_hypotheses
            if p>1.0:
                p=1.0
            logging.debug("P={} uncorrected={}".format(p,p_uncorrected))
            if p<threshold:
                res = {'c':cls,'p':p,'p_uncorrected':p_uncorrected}
                if labels:
                    res['n'] = self.ontology.label(cls)
                results.append(res)
            
        results = sorted(results, key=lambda x:x['p'])
        return results
            
    def jaccard_similarity(self,s1,s2):
        """
        Calculate jaccard index of inferred associations of two subjects

        |ancs(s1) /\ ancs(s2)|
        ---
        |ancs(s1) \/ ancs(s2)|

        """
        a1 = self.inferred_types(s1)
        a2 = self.inferred_types(s2)
        num_union = len(a1.union(a2))
        if num_union == 0:
            return 0.0
        return len(a1.intersection(a2)) / num_union

class NamedEntity():
    """
    E.g. a gene etc
    """

    def __init__(self, id, label=None, taxon=None):
        self.id=id
        self.label=label
        self.taxon=taxon

class AssociationSetMetadata():
    """
    Information about how an association set is derived
    """

    def __init__(self, id=None, taxon=None, evidence=None, subject_category=None, object_category=None):
        self.id=id
        self.taxon=taxon
        