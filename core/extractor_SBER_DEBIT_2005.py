import exceptions
import re
from datetime import datetime
from pprint import pprint


from utils import get_float_from_money
from utils import split_Sberbank_line

from extractor import Extractor

class SBER_DEBIT_2005(Extractor):

    def get_period_balance(self)->str:
        """
        функция ищет в тексте значения "СУММА ПОПОЛНЕНИЙ" и "СУММА СПИСАНИЙ" и возвращает раницу
        используется для контрольной проверки вычислений

        :param PDF_text:
        :return:
        """

        if (res := re.search(r'СУММА ПОПОЛНЕНИЙ\t(\d[\d\s]*\,\d\d)', self.pdf_text,
                             re.MULTILINE)):
            summa_popolneniy = res.group(1)
        else:
            raise exceptions.InputFileStructureError(
                'Не найдено значение "СУММА ПОПОЛНЕНИЙ"')

        if (res := re.search(r'СУММА СПИСАНИЙ\t(\d[\d\s]*\,\d\d)', self.pdf_text,
                             re.MULTILINE)):
            summa_spisaniy = res.group(1)
        else:
            raise exceptions.InputFileStructureError(
                'Не найдено значение "СУММА СПИСАНИЙ "')

        # print(f"{summa_popolneniy=}")
        # print(f"{summa_spisaniy=}")
        summa_popolneniy = get_float_from_money(summa_popolneniy)
        summa_spisaniy = get_float_from_money(summa_spisaniy)

        return summa_popolneniy - summa_spisaniy

    def split_text_on_entries(self)->list[str]:
        """
        разделяет текстовый файл на отдельные записи

        пример одной записи
        ---------------------------------------------------------------------------------------------------------
        29.08.2019 10:04     GETT     1 189,40     8 087,13
        29.08.2019 / 278484     Отдых и развлечения
        ----------------------------------------------------------------------------------------------------------

        ещё один пример (с 3 линиями)
        ---------------------------------------------------------------------------------------------------------
        26.07.2019 02:04      ПЛАТА ЗА ОБСЛУЖИВАНИЕ БАНКОВСКОЙ     750,00     -750,00
        КАРТЫ  (ЗА ПЕРВЫЙ ГОД)
        05.08.2019 / -     Прочие операции
        ---------------------------------------------------------------------------------------------------------

        """
        # extracting entries (operations) from text file on
        individual_entries = re.findall(r"""
        \d\d\.\d\d\.\d\d\d\d\s\d\d:\d\d               # Date and time like 25.04.1991 18:31                                        
        [\s\S]*?                                      # any character, including new line. !!None-greedy!! See URL why [\s\S] is used https://stackoverflow.com/a/33312193
        \d\d\.\d\d\.\d\d\d\d\s/                       # date with forward stash like '25.12.2019 /' 
        .*?\n                                         # everything till end of the line
        """,
                                        self.pdf_text, re.VERBOSE)

        if len(individual_entries) == 0:
            raise exceptions.InputFileStructureError(
                "Не обнаружена ожидаемая структора данных: не найдено ни одной трасакции")

        return individual_entries

    def decompose_entry_to_dict(self, entry:str)->dict:
        """
        Выделяем данные из одной записи в dictionary

        пример одной записи
        ---------------------------------------------------------------------------------------------------------
        29.08.2019 10:04 -> GETT -> 1 189,40 -> 8 087,13
        29.08.2019 / 278484 -> Отдых и развлечения
        ----------------------------------------------------------------------------------------------------------

        ещё один пример (с 3 линиями)
        ---------------------------------------------------------------------------------------------------------
        26.07.2019 02:04 -> ПЛАТА ЗА ОБСЛУЖИВАНИЕ БАНКОВСКОЙ -> 750,00 -> -750,00
        КАРТЫ  (ЗА ПЕРВЫЙ ГОД)
        05.08.2019 / - -> Прочие операции
        ---------------------------------------------------------------------------------------------------------
        В этом примере:

        result['operation_date'] = '26.07.2019 02:04'
        result['description'] = 'ПЛАТА ЗА ОБСЛУЖИВАНИЕ БАНКОВСКОЙ КАРТЫ  (ЗА ПЕРВЫЙ ГОД)'
        result['value_account_currency'] = -750.00
        result['remainder_account_currency'] = - 750.00
        result['processing_date'] = '05.08.2019'
        result['authorisation_code'] = '-'
        """
        lines = entry.split('\n')
        lines = list(filter(None, lines))

        result = {}
        # ************** looking at the 1st line

        line_parts = split_Sberbank_line(lines[0])

        result['operation_date'] = line_parts[0]
        result['description'] = line_parts[1]
        result['value_account_currency'] = get_float_from_money(line_parts[2],
                                                                True)
        result['remainder_account_currency'] = get_float_from_money(
            line_parts[3])

        # ************* looking at lines between 1st and the last
        sublines = lines[1:-1]
        for line in sublines:
            line_parts = split_Sberbank_line(line)
            if len(line_parts) != 1:
                raise exceptions.SberbankPDFtext2ExcelError(
                    "Line is expected to have only one part :" + line)
            result['description'] = result['description'] + ' ' + line_parts[0]

        # ************* looking at the last line
        line_parts = split_Sberbank_line(lines[-1])

        if len(line_parts) < 2 or len(line_parts) > 3:
            raise exceptions.SberbankPDFtext2ExcelError(
                "Line is expected to 2 or parts :" + line)

        result['processing_date'] = line_parts[0][0:10]
        result['authorisation_code'] = line_parts[0][13:]
        result['category'] = line_parts[1]

        if len(line_parts) == 3:
            found = re.search(r'[(](.*?)(\w\w\w)[)]', line_parts[
                2])  # processing string like (33,31 EUR)
            if found:
                result['value_operational_currency'] = get_float_from_money(
                    found.group(1), True)
                result['operational_currency'] = found.group(2)
            else:
                raise exceptions.InputFileStructureError(
                    "Ошибка в обработке текста. Ожидалась струтура типа (33,31 EUR), получено: " + line)

        return result

    def get_column_name_for_balance_calculation(self)->str:
        return 'value_account_currency'

    def get_columns_info(self)->dict:
        """
        Returns full column names in the order they shall appear in Excel
        The keys in dictionary shall correspond to keys of the result of the function self.decompose_entry_to_dict()
        """
        return {'operation_date': 'Дата операции',
                'processing_date': 'Дата обработки',
                'authorisation_code': 'Код авторизации',
                'description': 'Описание операции',
                'category': 'Категория',
                'value_account_currency': 'Сумма в валюте счёта',
                'value_operational_currency': 'Сумма в валюте операции',
                'operational_currency': 'Валюта операции',
                'remainder_account_currency': 'Остаток по счёту в валюте счёта'}


if __name__ == '__main__':

    txt_file = r'C:\_code\py\Sberbank2Excel_no_github\20210724_20210720_20210724_2107_Stavropol_.txt'

    with open(txt_file, encoding='utf-8') as f:
        txt_file_content = f.read()

    converter = SBER_DEBIT_2005(txt_file_content)

    print(f"period_balance = {converter.get_period_balance()}")

    for entry in converter.get_entries():
        print('*'*20)
        pprint(entry)

    print(f"check_support = {converter.check_support()}")