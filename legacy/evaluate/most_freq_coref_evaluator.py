from base_evaluator import BaseEvaluator


class MostFreqCorefEvaluator(BaseEvaluator):
    def __init__(self):
        BaseEvaluator.__init__(self)

    @staticmethod
    def is_most_freq_coref(coref_idx, coref_freqs):
        coref_freqs[coref_idx] -= 1
        most_freq_coref_idx = coref_freqs.index(max(coref_freqs))
        coref_freqs[coref_idx] += 1
        return coref_idx == most_freq_coref_idx

    def print_debug_message(self):
        return 'Evaluation based on most frequent coreference chain, ' \
               'ignore_first_mention = {}:'.format(self.ignore_first_mention)

    def evaluate_script(self, script):
        num_choices = len(script.corefs)
        coref_freqs = [len(coref.mentions) for coref in script.corefs]
        for event in script.events:
            for label, arg in event.get_all_args_with_coref():
                # do not evaluate the first mention of a coref chain,
                # as per the evaluation framework of implicit argument,
                # we must have other mentions in previous sentences
                if (not self.ignore_first_mention) \
                        or arg.mention.mention_idx != 0:
                    self.eval_stats.add_eval_result(
                        label,
                        self.is_most_freq_coref(arg.coref.idx, coref_freqs),
                        num_choices)
        return self.eval_stats
