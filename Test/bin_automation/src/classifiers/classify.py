import pandas as pd
from pathlib import Path
from ..validators.validate_bin import BINValidator

class BINClassifier:
    def __init__(self):
        self.validator = BINValidator()
        self.country_ranges = {
            'US': [(400000, 499999)],
            'BR': [(500000, 509999)],
            'MX': [(450000, 459999)],
            # Agregar más rangos según se necesite
        }
        
        self.card_types = {
            '4': 'VISA',
            '5': 'MASTERCARD',
            '3': 'AMEX',
            # Agregar más tipos según se necesite
        }

    def get_country(self, bin_number: str) -> str:
        """
        Determina el país del BIN basado en rangos predefinidos
        """
        if not isinstance(bin_number, str):
            bin_number = str(bin_number)
            
        bin_int = int(bin_number[:6])
        
        for country, ranges in self.country_ranges.items():
            for start, end in ranges:
                if start <= bin_int <= end:
                    return country
        return 'UNKNOWN'

    def get_card_type(self, bin_number: str) -> str:
        """
        Determina el tipo de tarjeta basado en el primer dígito
        """
        if not isinstance(bin_number, str):
            bin_number = str(bin_number)
            
        return self.card_types.get(bin_number[0], 'UNKNOWN')

    def classify_bin(self, bin_number: str) -> dict:
        """
        Clasifica un BIN y retorna toda su información
        """
        return {
            'bin': bin_number,
            'country': self.get_country(bin_number),
            'card_type': self.get_card_type(bin_number),
            'validation_level': self.validator.get_validation_level(bin_number)
        }

def main():
    try:
        # Cargar datos normalizados
        input_path = Path('data/input/normalized.csv')
        df = pd.read_csv(input_path)
        
        # Clasificar BINs
        classifier = BINClassifier()
        classified_data = [classifier.classify_bin(bin_number) 
                         for bin_number in df['bin']]
        
        # Crear DataFrame con resultados
        result_df = pd.DataFrame(classified_data)
        
        # Guardar resultados
        output_path = Path('data/output/classified.csv')
        result_df.to_csv(output_path, index=False)
        print(f"Datos clasificados guardados en {output_path}")
        
    except Exception as e:
        print(f"Error durante la clasificación: {e}")
        raise

if __name__ == '__main__':
    main() 