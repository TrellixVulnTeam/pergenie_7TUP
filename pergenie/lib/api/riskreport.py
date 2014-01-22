import sys, os
import re
import datetime
import zipfile
from pprint import pformat, pprint
from pymongo import MongoClient
from django.conf import settings
from lib.api.gwascatalog import GWASCatalog
gwascatalog = GWASCatalog()
from lib.api.genomes import Genomes
genomes = Genomes()
from utils import clogging
log = clogging.getColorLogger(__name__)
from riskreport_base import RiskReportBase

class RiskReport(RiskReportBase):
    """
    Django and MongoDB version of RiskReport

    - Depends on Django
    - Depneds on MongoDB

    """

    def __init__(self):
        c = MongoClient(host=settings.MONGO_URI)
        self.db = c['pergenie']
        self.data_info = self.db['data_info']

    def is_uptodate(self, info):
        """Check if user's risk report is up-to-date.
        """
        user_data_info = self.data_info.find_one({'user_id': info['user_id'], 'name': info['name']})
        last_riskreport_date = user_data_info.get('riskreport')

        if not last_riskreport_date:
            return False

        latest_gwascatalog_date = self.db['catalog_info'].find_one({'status': 'latest'})['date']
        delta_days = (latest_gwascatalog_date - last_riskreport_date).days

        return bool(delta_days < settings.UPDATE_SPAN)

    def get_file_uuid(self, user_id, file_name):
        file_uuid = self.data_info.find_one({'user_id': user_id, 'name': file_name})['file_uuid']
        return file_uuid

    def get_riskreport(self, user_id, file_name):
        file_uuid = self.get_file_uuid(user_id, file_name)
        riskreport = self.db['riskreport'][file_uuid]
        return riskreport

    def write_riskreport(self, user_id, file_infos, ext='tsv', force_uptade=False):
        """Write out riskreport(.tsv|.csv) as .zip
        """

        fout_paths = []

        delimiter = {'tsv': '\t'}  # 'csv': ','
        traits, traits_ja, traits_category, _ = gwascatalog.get_traits_infos(as_dict=True)
        today = str(datetime.date.today())

        log.debug(file_infos)
        log.info('Try to write {0} file(s)...'.format(len(file_infos)))

        for file_info in file_infos:
            RR_dir = os.path.join(settings.UPLOAD_DIR, user_id, 'RR')
            if not os.path.exists(RR_dir):
                os.makedirs(RR_dir)
            fout_name = 'RR-{file_name}.{ext}'.format(file_name=file_info['name'], ext=ext)
            fout_path = os.path.join(RR_dir, fout_name)
            fout_paths.append(fout_path)

            # Skip writing if file already exists
            # if os.path.exists(fout_path) and not force_uptade:
            #     log.debug('skip writing (use existing file)')
            #     continue

            tmp_riskreport = self.db['riskreport'][file_info['file_uuid']]

            with open(fout_path, 'w') as fout:
                header = ['traits', 'RR', 'pubmed_link', 'snps']
                print >>fout, delimiter[ext].join(header)

                for trait in traits:
                    content = [trait]
                    #       = [trait, traits_ja[trait], traits_category[trait]]

                    gwas = gwascatalog.get_latest_catalog()  ##
                    found = tmp_riskreport.find_one({'trait': trait})
                    if found:
                        risk = str(found['RR'])
                        snps = ';'.join(['rs'+str(x['snp']) for x in found['studies'] if x['study'] == found['highest']])
                        link = gwas.find_one({'study': found['highest']})['pubmed_link']
                    else:
                        risk = ''
                        snps = ''
                        link = ''

                    content += [risk, link, snps]

                    # Write out only diseases
                    if traits_category[trait] != 'Disease':
                        continue
                    # Write out only if RR exists
                    if not risk:
                        continue

                    print >>fout, delimiter[ext].join(content)

        # Zip (py26)
        log.info('Zipping {0} file(s)...'.format(len(fout_paths)))

        if len(fout_paths) == 1:
            fout_zip_name = '{file_name}.zip'.format(file_name=os.path.basename(fout_paths[0]))
        else:
            fout_zip_name = 'RR.zip'
        fout_zip_path = os.path.join(RR_dir, fout_zip_name)
        fout_zip = zipfile.ZipFile(fout_zip_path, 'w', zipfile.ZIP_DEFLATED)
        for fout_path in fout_paths:
            fout_zip.write(fout_path, os.path.join(user_id, os.path.basename(fout_path)))
        fout_zip.close()

        return fout_zip_path

    def get_all_riskreports(self, user_id):
        all_riskreports = []
        user_files = genomes.get_data_infos(user_id)
        for file_uuid in [x['file_uuid'] for x in user_files]:
            all_riskreports.append(self.db['riskreport'][file_uuid])
        return all_riskreports

    def import_riskreport(self, info):
        if info['user_id'].startswith(settings.DEMO_USER_ID): info['user_id'] = settings.DEMO_USER_ID

        # Get GWAS Catalog records for this population
        population = 'population:{0}'.format('+'.join(settings.POPULATION_MAP[info['population']]))
        catalog_records = gwascatalog.search_catalog_by_query(population, None).sort('trait', 1)
        catalog_map = {}
        found_id = 0
        snps_all = set()
        for record in catalog_records:
            if record['snps'] != 'na':
                snps_all.update([record['snps']])

                found_id += 1
                reported_genes = ', '.join([gene['gene_symbol'] for gene in record['reported_genes']])
                mapped_genes = ', '.join([gene['gene_symbol'] for gene in record['mapped_genes']])
                catalog_map[found_id] = record
                catalog_map[found_id].update({'rs': record['snps'],
                                              'reported_genes': reported_genes,
                                              'mapped_genes': mapped_genes,
                                              'chr': record['chr_id'],
                                              'freq': record['risk_allele_frequency'],
                                              'added': record['added'].date(),
                                              'date': record['date'].date()})

        # Get genotypes for these GWAS Catalog records
        # Case1: in catalog & in variants
        variants_map = genomes.get_genotypes(info['user_id'], info['name'], info['file_format'], list(snps_all), 'rs',
                                             check_ref_or_not=False)

        # Case2: in catalog, but not in variants. so genotype is homozygous of `ref` or `na`.
        for _id, _catalog in catalog_map.items():
            rs = _catalog['rs']
            if rs and rs != 'na' and (not rs in variants_map):
                variants_map[rs] = genomes._ref_or_na(rs, 'rs', info['file_format'], rec=_catalog)

        # Case3: TODO:

        # Get number of uniq studies for this population
        # & Get cover rate of GWAS Catalog for this population
        uniq_studies, uniq_snps = set(), set()
        n_available = 0
        for record in catalog_map.values():
            if not record['pubmed_id'] in uniq_studies:
                uniq_studies.update([record['pubmed_id']])

            if record['snp_id_current'] and record['snp_id_current'] not in uniq_snps:
                uniq_snps.update([record['snp_id_current']])

                if info['file_format'] == 'vcf_exome_truseq' and record['is_in_truseq']:
                    n_available += 1
                elif info['file_format'] == 'vcf_exome_iontargetseq' and record['is_in_iontargetseq']:
                    n_available += 1
                elif info['file_format'] == 'andme' and record['is_in_andme']:
                    n_available += 1

        log.debug('n_available: %s' % n_available)

        n_studies = len(uniq_studies)
        if info['file_format'] == 'vcf_whole_genome':
            catalog_cover_rate_for_this_population = 100
        else:
            catalog_cover_rate_for_this_population = round(100 * n_available / len(uniq_snps))

        # Calculate risk
        risk_store, risk_reports = self.risk_calculation(catalog_map, variants_map)

        # Set reliability rank
        tmp_risk_reports = dict()
        for trait,studies in risk_reports.items():
            tmp_risk_reports[trait] = {}

            for study,value in studies.items():
                record = risk_store[trait][study].values()[0]['catalog_map']
                r_rank = self._calc_reliability_rank(record)
                tmp_risk_reports[trait].update({study: [r_rank, value]})
        risk_reports = tmp_risk_reports

        # Import riskreport into MongoDB
        file_uuid = self.get_file_uuid(info['user_id'], info['name'])
        users_reports = self.db['riskreport'][file_uuid]
        if users_reports.find_one():
            self.db.drop_collection(users_reports)

        for trait, study_level_rank_and_values in risk_reports.items():
            # Get highest reriability study
            studies = list()
            for study, rank_and_values in study_level_rank_and_values.items():
                studies.append(dict(study=study, rank=rank_and_values[0], RR=rank_and_values[1]))
            highest = self._get_highest_priority_study(studies)

            # Get SNP level infos (RR, genotype, etc...)
            snp_level_records = list()
            for study, snp_level_sotres in risk_store[trait].items():
                for snp, snp_level_sotre in snp_level_sotres.items():
                    snp_level_records.append(dict(snp=snp,
                                                  RR=snp_level_sotre['RR'],  # snp-level
                                                  genotype=snp_level_sotre['variant_map'],  # snp-level
                                                  study=study,
                                                  rank=study_level_rank_and_values.get(study, ['na'])[0]  # study-level  # FIXME: why key-error occur?
                                              ))

            users_reports.insert(dict(trait=trait,
                                      RR=highest['RR'],
                                      rank=highest['rank'],
                                      highest=highest['study'],
                                      studies=snp_level_records), upsert=True)

        # Update data_info
        self.data_info.update({'user_id': info['user_id'], 'name': info['name']},
                              {"$set": {'riskreport': datetime.datetime.today(),
                                        'n_studies': n_studies,
                                        'catalog_cover_rate_for_this_population': catalog_cover_rate_for_this_population}}, upsert=True)


def _test():
    import doctest
    doctest.testmod()

if __name__ == '__main__':
    _test()
