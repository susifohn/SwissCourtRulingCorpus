import configparser
from scrc.preprocessing.name_to_gender import NameToGender
from scrc.preprocessing.extractors.procedural_participation_extractor import ProceduralParticipationExtractor
from scrc.preprocessing.extractors.court_composition_extractor import CourtCompositionExtractor

from root import ROOT_DIR
from scrc.preprocessing.extractors.citation_extractor import CitationExtractor
from scrc.preprocessing.extractors.cleaner import Cleaner
from scrc.dataset_creation.citation_dataset_creator import CitationDatasetCreator
from scrc.dataset_creation.criticality_dataset_creator import CriticalityDatasetCreator
from scrc.dataset_creation.judgment_dataset_creator import JudgmentDatasetCreator
from scrc.preprocessing.text_to_database import TextToDatabase
from scrc.preprocessing.extractors.judgement_extractor import JudgementExtractor
from scrc.preprocessing.extractors.lower_court_extractor import LowerCourtExtractor
from scrc.preprocessing.scraper import Scraper, base_url
from scrc.preprocessing.extractors.section_splitter import SectionSplitter
from scrc.preprocessing.nlp_pipeline_runner import NlpPipelineRunner
from scrc.preprocessing.count_computer import CountComputer

from scrc.preprocessing.external_corpora.jureko_processor import JurekoProcessor
from scrc.preprocessing.external_corpora.slc_processor import SlcProcessor
from scrc.preprocessing.external_corpora.wikipedia_processor import WikipediaProcessor
from scrc.utils.decorators import slack_alert

"""
This file aggregates all the pipeline components and can be a starting point for running the entire pipeline.

Approach:
- Scrape data into spider folders
- Extract text and metadata content (save to Postgres DB because of easy interoperability with pandas (filtering and streaming))
- Clean text  (keep raw content in db)
- Split BGer into sections (from html_raw)
- Extract BGer citations (from html_raw) using "artref" tags
- Extract judgements
- Process each text with spacy, save doc to disk and store path in db, store num token count in separate db col
- Compute lemma counts and save aggregates in separate tables
- Create the smaller datasets derived from SCRC with the available metadata
"""


@slack_alert
def main():
    """
    Runs the entire pipeline.
    :return:
    """
    # faulthandler.enable()  # can print a minimal threaddump in case of external termination

    config = configparser.ConfigParser()
    config.read(ROOT_DIR / 'config.ini')  # this stops working when the script is called from the src directory!

    process_scrc(config)

    process_external_corpora(config)


def process_scrc(config):
    """
    Processes everything related to the core SCRC corpus
    :param config:
    :return:
    """
    construct_base_dataset(config)

    create_specialized_datasets(config)


def create_specialized_datasets(config):
    # TODO for identifying decisions in the datasets it would make sense to assign them a uuid.
    #  This could be based on other properties. We just need to make sure that we don't have any duplicates

    judgment_dataset_creator = JudgmentDatasetCreator(config)
    judgment_dataset_creator.create_dataset()

    citation_dataset_creator = CitationDatasetCreator(config)
    citation_dataset_creator.create_dataset()

    criticality_dataset_creator = CriticalityDatasetCreator(config)
    criticality_dataset_creator.create_dataset()


def construct_base_dataset(config):
    scraper = Scraper(config)
    scraper.download_subfolders(base_url + "docs/")

    extractor = TextToDatabase(config)
    extractor.build_dataset()

    cleaner = Cleaner(config)
    cleaner.clean()

    section_splitter = SectionSplitter(config)
    section_splitter.start()

    citation_extractor = CitationExtractor(config)
    citation_extractor.start()

    judgement_extractor = JudgementExtractor(config)
    judgement_extractor.start()

    lower_court_extractor = LowerCourtExtractor(config)
    lower_court_extractor.start()

    court_composition_extractor = CourtCompositionExtractor(config)
    court_composition_extractor.start()

    procedural_participation_extractor = ProceduralParticipationExtractor(config)
    procedural_participation_extractor.start()

    name_to_gender = NameToGender(config)
    name_to_gender.start()

    nlp_pipeline_runner = NlpPipelineRunner(config)
    nlp_pipeline_runner.run_pipeline()

    count_computer = CountComputer(config)
    count_computer.run_pipeline()


def process_external_corpora(config):
    """
    Processes external corpora which can be compared to SCRC.
    :param config:
    :return:
    """
    wikipedia_processor = WikipediaProcessor(config)
    wikipedia_processor.process()

    jureko_processor = JurekoProcessor(config)
    jureko_processor.process()

    slc_processor = SlcProcessor(config)
    slc_processor.process()


if __name__ == '__main__':
    main()
