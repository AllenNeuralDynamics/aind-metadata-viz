import pandas as pd


def compute_count_true(df):
    """For each column, compute the count of true values and return as a
    longform dataframe

    Parameters
    ----------
    df : dataframe
        Dataframe of "absent"/"present"/"excluded" values
    """

    categories = ['absent', 'present', 'excluded']

    # Apply value_counts to each column and fill missing categories with 0
    count_df = pd.DataFrame({col: df[col].value_counts() for col in df.columns}).fillna(0)

    # Reindex with categories to ensure all categories are present
    count_df = count_df.reindex(categories).fillna(0)

    # Transpose so that columns are "absent", "present", "excluded" with count per original column
    count_df = count_df.transpose()

    long_df = count_df.reset_index().melt(id_vars='index', var_name='category', value_name='count')

    # Rename 'index' to something more meaningful like 'column'
    long_df.rename(columns={'index': 'column'}, inplace=True)
    return long_df
