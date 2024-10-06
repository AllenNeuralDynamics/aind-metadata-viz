from enum import Enum


class MetaState(str, Enum):
    VALID = "valid"
    PRESENT = "present"
    MISSING = "missing"
    EXCLUDED = "excluded"


def compute_count_true(df):
    """For each column, compute the count of true values and return as a
    longform dataframe

    Parameters
    ----------
    df : dataframe
        Dataframe of False/True values
    """
    sum_df = df.sum().to_frame(name="present")
    sum_df["missing"] = df.shape[0] - sum_df["present"]

    sum_longform_df = sum_df.reset_index().melt(
        id_vars="index", var_name="status", value_name="sum"
    )
    return sum_longform_df
