import gc
from pathlib import Path
import glob

import spacy
from spacy.tokens import DocBin
from tqdm import tqdm
import pandas as pd
import configparser
from scrc.dataset_construction.dataset_constructor_component import DatasetConstructorComponent
from root import ROOT_DIR
from scrc.utils.decorators import slack_alert
from scrc.utils.log_utils import get_logger

# import scrc.utils.monkey_patch  # prevent memory leak with pandas

# IMPORTANT: make sure you download these models first with: python -m spacy download de_dep_news_trf
import de_core_news_lg, fr_core_news_lg, it_core_news_lg

from scrc.utils.main_utils import chunker


class SpacyPipelineRunner(DatasetConstructorComponent):
    """
    Runs the entire spacy pipeline for each text and saves it into the MongoDB.
    This brings the advantage, that we have the heavy computation done in advance,
    and can then use the spacy objects directly in our analysis.
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.logger = get_logger(__name__)

        self.models = {
            'de': 'de_core_news_lg',
            'fr': 'fr_core_news_lg',
            'it': 'it_core_news_lg'
        }
        # tag, pos and lemma are enough for now
        self.disable_pipes = ['senter', 'ner', 'attribute_ruler', 'textcat']
        self.active_model = None

    def load_spacy_model(self, model_name, disable_pipes):
        return spacy.load(model_name, disable=disable_pipes)

    @slack_alert
    def run_pipeline(self):
        self.logger.info("Started running spacy pipeline on the texts")
        for lang in self.languages:
            self.logger.info(f"Processing language {lang}")
            self.logger.info("Loading spacy model")
            self.active_model = self.load_spacy_model(self.models[lang], self.disable_pipes)
            self.active_model.max_length = 2000000  # increase max length for long texts

            in_lang_dir = self.split_subdir / lang  # input dir
            out_lang_dir = self.create_dir(self.spacy_subdir, lang)  # output dir

            chamber_list = [Path(chamber).stem for chamber in glob.glob(f"{str(in_lang_dir)}/*.parquet")]
            self.logger.info(f"Found {len(chamber_list)} chambers in total")

            chambers_processed_path = out_lang_dir / "chambers_processed.txt"
            if not chambers_processed_path.exists():
                chambers_processed_path.touch()
            chambers_processed = chambers_processed_path.read_text().split("\n")
            self.logger.info(f"Found {len(chambers_processed)} chamber(s) already processed: {chambers_processed}")

            chambers_not_yet_processed = set(chamber_list) - set(chambers_processed)
            self.logger.info(
                f"Still {len(chambers_not_yet_processed)} chamber(s) remaining to process: {chambers_not_yet_processed}")

            self.process_chamber(chambers_not_yet_processed, chambers_processed_path, in_lang_dir, out_lang_dir)

            self.active_model.vocab.to_disk(out_lang_dir / f"_vocab_{lang}.spacy")

        self.logger.info("Finished running spacy pipeline on the texts")

    def process_chamber(self, chambers_not_yet_processed, chambers_processed_path, in_lang_dir, out_lang_dir):
        for chamber in chambers_not_yet_processed:
            df = pd.read_parquet(in_lang_dir / (chamber + ".parquet"))
            self.logger.info(f"Processing the {len(df.index)} decisions from chamber {chamber}")

            # according to docs you should aim for a partition size of 100MB
            # 1 court decision takes approximately between around 10KB and 100KB of RAM when loaded into memory
            # The spacy doc takes about 25x the size of a court decision
            self.run_spacy_pipeline(df, chamber, out_lang_dir)

            with chambers_processed_path.open("a") as f:
                f.write(chamber + "\n")

            del df
            gc.collect()

    def run_spacy_pipeline(self, df: pd.DataFrame, chamber: str, base_dir: Path, chunk_size=1000, override=False):
        """
        Creates and saves the docs generated by the spacy pipeline.
        """
        first_chunk_path = self.get_chunk_path(base_dir, chamber, 0)
        # if the first chunked df does not exist or we want to override it
        if override or not first_chunk_path.exists():
            # split df into chunks
            chunks = [df[i:i + chunk_size] for i in range(0, df.shape[0], chunk_size)]
            for chunk_num, chunk in enumerate(chunks):
                path = self.get_chunk_path(base_dir, chamber, chunk_num)
                print(f"Processing chunk {chunk_num} and saving it to {path}")

                texts = chunk.text.tolist()
                docs = tqdm(self.active_model.pipe(texts, n_process=-1, batch_size=1), total=len(texts))
                doc_bytes = [doc.to_bytes() for doc in docs]
                chunk['spacy_doc_bytes'] = doc_bytes
                chunk.to_parquet(path)

                del chunk
                gc.collect()
        else:
            print(f"Preprocessed docs already exist at {first_chunk_path}. To calculate again set 'override' to True.")

    def get_chunk_path(self, base_dir, chamber, chunk_num, extension="parquet"):
        chamber_dir = self.create_dir(base_dir, chamber)
        return chamber_dir / f"{chunk_num}.{extension}"


if __name__ == '__main__':
    config = configparser.ConfigParser()
    config.read(ROOT_DIR / 'config.ini')  # this stops working when the script is called from the src directory!

    spacy_pipeline_runner = SpacyPipelineRunner(config)
    spacy_pipeline_runner.run_pipeline()
