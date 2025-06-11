import pandas as pd
import os
from pathlib import Path

def load_input_file(filename='input.csv'):
    """
    Carga y normaliza el archivo de entrada
    """
    input_path = Path('data/input') / filename
    if not input_path.exists():
        raise FileNotFoundError(f"No se encontró el archivo {input_path}")
    
    df = pd.read_csv(input_path)
    return normalize_data(df)

def normalize_data(df):
    """
    Normaliza los datos de entrada:
    - Elimina espacios en blanco
    - Convierte BINs a string
    - Elimina duplicados
    """
    df = df.copy()
    if 'bin' in df.columns:
        df['bin'] = df['bin'].astype(str).str.strip()
    return df.drop_duplicates()

def main():
    try:
        df = load_input_file()
        # Guardar datos normalizados para siguiente paso
        output_path = Path('data/input/normalized.csv')
        df.to_csv(output_path, index=False)
        print(f"Datos normalizados guardados en {output_path}")
    except Exception as e:
        print(f"Error durante la ingesta de datos: {e}")
        raise

if __name__ == '__main__':
    main() 