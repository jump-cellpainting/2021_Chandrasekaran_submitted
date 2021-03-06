import os
import glob
import pandas as pd
import numpy as np
import random
from sklearn.utils.validation import check_is_fitted
from sklearn.utils import check_array, as_float_array
from sklearn.base import TransformerMixin, BaseEstimator
import kneed
import scipy
import seaborn as sns
import matplotlib.pyplot as plt
from sklearn.metrics import average_precision_score


def load_data(exp, plate, filetype):
    """load all data from a single experiment into a single dataframe"""
    path = os.path.join('../profiles',
                        f'{exp}',
                        f'{plate}',
                        f'*_{filetype}')
    files = glob.glob(path)
    df = pd.concat(pd.read_csv(_, low_memory=False) for _ in files)
    return df


def get_metacols(df):
    """return a list of metadata columns"""
    return [c for c in df.columns if c.startswith("Metadata_")]


def get_featurecols(df):
    """returna  list of featuredata columns"""
    return [c for c in df.columns if not c.startswith("Metadata")]


def get_metadata(df):
    """return dataframe of just metadata columns"""
    return df[get_metacols(df)]


def get_featuredata(df):
    """return dataframe of just featuredata columns"""
    return df[get_featurecols(df)]


def remove_negcon_empty_wells(df):
    """return dataframe of non-negative control wells"""
    df = (
        df.query('Metadata_control_type!="negcon"')
        .dropna(subset=['Metadata_broad_sample'])
        .reset_index(drop=True)
    )
    return df


def remove_empty_wells(df):
    """return dataframe of non-empty wells"""
    df = (
        df.dropna(subset=['Metadata_broad_sample'])
        .reset_index(drop=True)
    )
    return df


def concat_profiles(df1, df2):
    """Concatenate dataframes"""
    if df1.shape[0] == 0:
        df1 = df2.copy()
    else:
        frames = [df1, df2]
        df1 = pd.concat(frames, ignore_index=True, join="inner")

    return df1


def percent_score(null_dist, corr_dist, how):
    """
    Calculates the Percent strong or percent recall scores
    :param null_dist: Null distribution
    :param corr_dist: Correlation distribution
    :param how: "left", "right" or "both" for using the 5th percentile, 95th percentile or both thresholds
    :return: proportion of correlation distribution beyond the threshold
    """
    if how == 'right':
        perc_95 = np.nanpercentile(null_dist, 95)
        above_threshold = corr_dist > perc_95
        return np.mean(above_threshold.astype(float))*100, perc_95
    if how == 'left':
        perc_5 = np.nanpercentile(null_dist, 5)
        below_threshold = corr_dist < perc_5
        return np.mean(below_threshold.astype(float))*100, perc_5
    if how == 'both':
        perc_95 = np.nanpercentile(null_dist, 95)
        above_threshold = corr_dist > perc_95
        perc_5 = np.nanpercentile(null_dist, 5)
        below_threshold = corr_dist < perc_5
        return (np.mean(above_threshold.astype(float)) + np.mean(below_threshold.astype(float)))*100, perc_95, perc_5


def corr_between_replicates(df, group_by_feature):
    """
        Correlation between replicates
        Parameters:
        -----------
        df: pd.DataFrame
        group_by_feature: Feature name to group the data frame by
        Returns:
        --------
        list-like of correlation values
     """
    replicate_corr = []
    replicate_grouped = df.groupby(group_by_feature)
    for name, group in replicate_grouped:
        group_features = get_featuredata(group)
        corr = np.corrcoef(group_features)
        if len(group_features) == 1:  # If there is only one replicate on a plate
            replicate_corr.append(np.nan)
        else:
            np.fill_diagonal(corr, np.nan)
            replicate_corr.append(np.nanmedian(corr))  # median replicate correlation
    return replicate_corr


def corr_between_non_replicates(df, n_samples, n_replicates, metadata_compound_name):
    """
        Null distribution between random "replicates".
        Parameters:
        ------------
        df: pandas.DataFrame
        n_samples: int
        n_replicates: int
        metadata_compound_name: Compound name feature
        Returns:
        --------
        list-like of correlation values, with a  length of `n_samples`
    """
    df.reset_index(drop=True, inplace=True)
    null_corr = []
    while len(null_corr) < n_samples:
        compounds = random.choices([_ for _ in range(len(df))], k=n_replicates)
        sample = df.loc[compounds].copy()
        if len(sample[metadata_compound_name].unique()) == n_replicates:
            sample_features = get_featuredata(sample)
            corr = np.corrcoef(sample_features)
            np.fill_diagonal(corr, np.nan)
            null_corr.append(np.nanmedian(corr))  # median replicate correlation
    return null_corr


def correlation_between_modalities(modality_1_df, modality_2_df, modality_1, modality_2, metadata_common, metadata_perturbation):
    """
    Compute the correlation between two different modalities.
    :param modality_1_df: Profiles of the first modality
    :param modality_2_df: Profiles of the second modality
    :param modality_1: "Compound", "ORF" or "CRISPR"
    :param modality_2: "Compound", "ORF" or "CRISPR"
    :param metadata_common: feature that identifies perturbation pairs
    :param metadata_perturbation: perturbation name feature
    :return: list-like of correlation values
    """
    list_common_perturbation_groups = list(np.intersect1d(list(modality_1_df[metadata_common]), list(modality_2_df[metadata_common])))

    merged_df = pd.concat([modality_1_df, modality_2_df], ignore_index=False, join='inner')

    modality_1_df = merged_df.query('Metadata_modality==@modality_1')
    modality_2_df = merged_df.query('Metadata_modality==@modality_2')

    corr_modalities = []

    for group in list_common_perturbation_groups:
        modality_1_perturbation_df = modality_1_df.loc[modality_1_df[metadata_common] == group]
        modality_2_perturbation_df = modality_2_df.loc[modality_2_df[metadata_common] == group]

        for sample_1 in modality_1_perturbation_df[metadata_perturbation].unique():
            for sample_2 in modality_2_perturbation_df[metadata_perturbation].unique():
                modality_1_perturbation_sample_df = modality_1_perturbation_df.loc[modality_1_perturbation_df[metadata_perturbation] == sample_1]
                modality_2_perturbation_sample_df = modality_2_perturbation_df.loc[modality_2_perturbation_df[metadata_perturbation] == sample_2]

                modality_1_perturbation_profiles = get_featuredata(modality_1_perturbation_sample_df)
                modality_2_perturbation_profiles = get_featuredata(modality_2_perturbation_sample_df)

                corr = np.corrcoef(modality_1_perturbation_profiles, modality_2_perturbation_profiles)
                corr = corr[0:len(modality_1_perturbation_profiles), len(modality_1_perturbation_profiles):]
                corr_modalities.append(np.nanmedian(corr))  # median replicate correlation

    return corr_modalities


def null_correlation_between_modalities(modality_1_df, modality_2_df, modality_1, modality_2, metadata_common, metadata_perturbation, n_samples):
    """
    Compute the correlation between two different modalities.
    :param modality_1_df: Profiles of the first modality
    :param modality_2_df: Profiles of the second modality
    :param modality_1: "Compound", "ORF" or "CRISPR"
    :param modality_2: "Compound", "ORF" or "CRISPR"
    :param metadata_common: feature that identifies perturbation pairs
    :param metadata_perturbation: perturbation name feature
    :param n_samples: int
    :return:
    """
    list_common_perturbation_groups = list(np.intersect1d(list(modality_1_df[metadata_common]), list(modality_2_df[metadata_common])))

    merged_df = pd.concat([modality_1_df, modality_2_df], ignore_index=False, join='inner')

    modality_1_df = merged_df.query('Metadata_modality==@modality_1')
    modality_2_df = merged_df.query('Metadata_modality==@modality_2')

    null_modalities = []

    while len(null_modalities) < n_samples:
        perturbations = random.choices(list_common_perturbation_groups, k=2)
        modality_1_perturbation_df = modality_1_df.loc[modality_1_df[metadata_common] == perturbations[0]]
        modality_2_perturbation_df = modality_2_df.loc[modality_2_df[metadata_common] == perturbations[1]]

        for sample_1 in modality_1_perturbation_df[metadata_perturbation].unique():
            for sample_2 in modality_2_perturbation_df[metadata_perturbation].unique():
                modality_1_perturbation_sample_df = modality_1_perturbation_df.loc[modality_1_perturbation_df[metadata_perturbation] == sample_1]
                modality_2_perturbation_sample_df = modality_2_perturbation_df.loc[modality_2_perturbation_df[metadata_perturbation] == sample_2]

                modality_1_perturbation_profiles = get_featuredata(modality_1_perturbation_sample_df)
                modality_2_perturbation_profiles = get_featuredata(modality_2_perturbation_sample_df)

                corr = np.corrcoef(modality_1_perturbation_profiles, modality_2_perturbation_profiles)
                corr = corr[0:len(modality_1_perturbation_profiles), len(modality_1_perturbation_profiles):]
                null_modalities.append(np.nanmedian(corr))  # median replicate correlation

    return null_modalities


def null_correlation_between_modalities_list(modality_1_df, modality_2_df, modality_1, modality_2, metadata_common, metadata_perturbation, n_samples):
    """
    Compute the correlation between two different modalities.
    :param modality_1_df: Profiles of the first modality
    :param modality_2_df: Profiles of the second modality
    :param modality_1: "Compound", "ORF" or "CRISPR"
    :param modality_2: "Compound", "ORF" or "CRISPR"
    :param metadata_common: feature that identifies perturbation pairs
    :param metadata_perturbation: perturbation name feature
    :param n_samples: int
    :return:
    """
    list_common_perturbation_groups = list(np.intersect1d(list(modality_1_df[metadata_common]), list(modality_2_df[metadata_common])))

    metadata_common_list = f'{metadata_common}_list'

    merged_df = pd.concat([modality_1_df, modality_2_df], ignore_index=False, join='inner')

    modality_1_df = merged_df.query('Metadata_modality==@modality_1')
    modality_2_df = merged_df.query('Metadata_modality==@modality_2')

    null_modalities = []

    while len(null_modalities) < n_samples:
        overlap = True
        perturbations = random.choices(list_common_perturbation_groups, k=2)
        modality_1_perturbation_df = modality_1_df.loc[modality_1_df[metadata_common] == perturbations[0]]
        modality_2_perturbation_df = modality_2_df.loc[modality_2_df[metadata_common] == perturbations[1]]

        if modality_1 == "compound":
            modality_1_perturbation_list = np.unique(modality_1_perturbation_df.Metadata_gene_list.sum())
            if not perturbations[1] in modality_1_perturbation_list:
                overlap = False
        elif modality_1 == "compound":
            modality_2_perturbation_list = np.unique(modality_2_perturbation_df.Metadata_gene_list.sum())
            if not perturbations[0] in modality_2_perturbation_list:
                overlap = False

        if not overlap:
            for sample_1 in modality_1_perturbation_df[metadata_perturbation].unique():
                for sample_2 in modality_2_perturbation_df[metadata_perturbation].unique():
                    modality_1_perturbation_sample_df = modality_1_perturbation_df.loc[modality_1_perturbation_df[metadata_perturbation] == sample_1]
                    modality_2_perturbation_sample_df = modality_2_perturbation_df.loc[modality_2_perturbation_df[metadata_perturbation] == sample_2]

                    modality_1_perturbation_profiles = get_featuredata(modality_1_perturbation_sample_df)
                    modality_2_perturbation_profiles = get_featuredata(modality_2_perturbation_sample_df)

                    corr = np.corrcoef(modality_1_perturbation_profiles, modality_2_perturbation_profiles)
                    corr = corr[0:len(modality_1_perturbation_profiles), len(modality_1_perturbation_profiles):]
                    null_modalities.append(np.nanmedian(corr))  # median replicate correlation

    return null_modalities


class ZCA_corr(BaseEstimator, TransformerMixin):
    def __init__(self, copy=False):
        self.copy = copy

    def estimate_regularization(self, eigenvalue):
        x = [_ for _ in range(len(eigenvalue))]
        kneedle = kneed.KneeLocator(x, eigenvalue, S=1.0, curve='convex', direction='decreasing')
        reg = eigenvalue[kneedle.elbow]/10.0
        return reg # The complex part of the eigenvalue is ignored

    def fit(self, X, y=None):
        """
        Compute the mean, sphering and desphering matrices.
        Parameters
        ----------
        X : array-like with shape [n_samples, n_features]
            The data used to compute the mean, sphering and desphering
            matrices.
        """
        X = check_array(X, accept_sparse=False, copy=self.copy, ensure_2d=True)
        X = as_float_array(X, copy=self.copy)
        self.mean_ = X.mean(axis=0)
        X_ = X - self.mean_
        cov = np.dot(X_.T, X_) / (X_.shape[0] - 1)
        V = np.diag(cov)
        df = pd.DataFrame(X_)
        corr = np.nan_to_num(df.corr()) # replacing nan with 0 and inf with large values
        G, T, _ = scipy.linalg.svd(corr)
        regularization = self.estimate_regularization(T.real)
        t = np.sqrt(T.clip(regularization))
        t_inv = np.diag(1.0 / t)
        v_inv = np.diag(1.0/np.sqrt(V.clip(1e-3)))
        self.sphere_ = np.dot(np.dot(np.dot(G, t_inv), G.T), v_inv)
        return self

    def transform(self, X, y=None, copy=None):
        """
        Parameters
        ----------
        X : array-like with shape [n_samples, n_features]
            The data to sphere along the features axis.
        """
        check_is_fitted(self, "mean_")
        X = as_float_array(X, copy=self.copy)
        return np.dot(X - self.mean_, self.sphere_.T)


def sphere_plate_zca_corr(plate):
    """
    sphere each plate to the DMSO negative control values
    Parameters:
    -----------
    plate: pandas.DataFrame
        dataframe of a single plate's featuredata and metadata
    Returns:
    -------
    pandas.DataFrame of the same shape as `plate`
    """
    # sphere featuredata to DMSO sphering matrix
    spherizer = ZCA_corr()
    dmso_df = plate.loc[plate.Metadata_control_type=="negcon"]
    dmso_vals = get_featuredata(dmso_df).to_numpy()
    all_vals = get_featuredata(plate).to_numpy()
    spherizer.fit(dmso_vals)
    sphered_vals = spherizer.transform(all_vals)
    # concat with metadata columns
    feature_df = pd.DataFrame(
        sphered_vals, columns=get_featurecols(plate), index=plate.index
    )
    metadata = get_metadata(plate)
    combined = pd.concat([metadata, feature_df], axis=1)
    assert combined.shape == plate.shape
    return combined


def distribution_plot(df, output_file, metric):
    """
    Generates the correlation distribution plots
    Parameters:
    -----------
    df: pandas.DataFrame
        dataframe containing the data points of replicate and null correlation distributions, description, Percent score and threshold values.
    output_file: str
        name of the output file. The file will be output to the figures/ folder.
    metric: str
        Percent Replicating or Percent Matching
    Returns:
    -------
    None
    """

    if metric == 'Percent Replicating':
        metric_col = 'Percent_Replicating'
        null = 'Null_Replicating'
        null_label = 'non-replicates'
        signal = 'Replicating'
        signal_label = 'replicates'
        x_label = 'Replicate correlation'
    elif metric == 'Percent Matching':
        metric_col = 'Percent_Matching'
        null = 'Null_Matching'
        null_label = 'non-matching perturbations'
        signal = 'Matching'
        signal_label = 'matching perturbations'
        x_label = 'Correlation between perturbations targeting the same gene'

    n_experiments = len(df)

    plt.rcParams['figure.facecolor'] = 'white'  # Enabling this makes the figure axes and labels visible in PyCharm Dracula theme
    plt.figure(figsize=[12, n_experiments * 6])

    for i in range(n_experiments):
        plt.subplot(n_experiments, 1, i + 1)
        plt.hist(df.loc[i, f'{null}'], label=f'{null_label}', density=True, bins=20, alpha=0.5)
        plt.hist(df.loc[i, f'{signal}'], label=f'{signal_label}', density=True, bins=20, alpha=0.5)
        plt.axvline(df.loc[i, 'Value_95'], label='95% threshold')
        plt.legend(fontsize=20)
        plt.title(
            f"{df.loc[i, 'Description']}\n" +
            f"{metric} = {df.loc[i, f'{metric_col}']}",
            fontsize=25
        )
        plt.ylabel("density", fontsize=25)
        plt.xlabel(f"{x_label}", fontsize=25)
        plt.xticks(fontsize=20)
        plt.yticks(fontsize=20)
        sns.despine()
    plt.tight_layout()
    plt.savefig(f'figures/{output_file}')


def consensus(profiles_df, group_by_feature):
    """
    Computes the median consensus profiles.
    Parameters:
    -----------
    profiles_df: pandas.DataFrame
        dataframe of profiles
    group_by_feature: str
        Name of the column
    Returns:
    -------
    pandas.DataFrame of the same shape as `plate`
    """

    metadata_df = (
        get_metadata(profiles_df)
            .drop_duplicates(subset=[group_by_feature])
    )

    feature_cols = [group_by_feature] + get_featurecols(profiles_df)
    profiles_df = profiles_df[feature_cols].groupby([group_by_feature]).median().reset_index()

    profiles_df = (
        metadata_df.merge(profiles_df, on=group_by_feature)
    )

    return profiles_df


class PrecisionScores(object):
    """
    Calculate the precision scores for information retrieval.
    """
    def __init__(self, profile1, profile2, group_by_feature, within=False, rank=False, anti_correlation=False, k=1, challenge_negcon=False):
        """
        Parameters:
        -----------
        profile1: pandas.DataFrame
            dataframe of profiles
        profile2: pandas.DataFrame
            dataframe of profiles
        group_by_feature: str
            Name of the column
        within: bool, default: False
            Whether profile1 and profile2 are the same dataframe or not.
        rank: bool, default: False
            Whether to use rank of the correlation values or not.
        anti_correlation: book, default: False
            Whether both anti-correlation and correlation are used in the calculation
        k: int, default: 1
            value at which precision is calculated.
        challenge_negcon: bool, default:  False
            Whether to calculate precision scores by challenging negcon.
        """
        self.sample_feature = 'Metadata_sample_id'
        self.control_type_feature = 'Metadata_control_type'
        self.feature = group_by_feature
        self.within = within
        self.rank = rank
        self.anti_correlation = anti_correlation
        self.k = k
        self.challenge_negcon = challenge_negcon

        self.profile1 = self.process_profiles(profile1)
        self.profile2 = self.process_profiles(profile2)

        self.map1 = self.profile1[[self.feature, self.sample_feature, self.control_type_feature]].copy()
        self.map2 = self.profile2[[self.feature, self.sample_feature, self.control_type_feature]].copy()

        self.corr = self.compute_correlation()
        self.truth_matrix = self.create_truth_matrix()

        self.ap_sample = self.calculate_average_precision_per_sample()
        self.ap_group = self.calculate_average_precision_score_per_group(self.ap_sample)
        self.map = self.calculate_mean_average_precision_score(self.ap_group)

        self.pk_sample = self.calculate_average_precision_at_k_per_sample()
        self.pk_group = self.calculate_average_precision_score_per_group(self.pk_sample)
        self.mpk = self.calculate_mean_average_precision_score(self.pk_group)

        self.pr_sample = self.calculate_average_precision_at_r_per_sample()
        self.pr_group = self.calculate_average_precision_score_per_group(self.pr_sample)
        self.mpr = self.calculate_mean_average_precision_score(self.pr_group)

    def process_profiles(self, _profile):
        """
        Add sample id column to profiles.
        Parameters:
        -----------
        _profile: pandas.DataFrame
            dataframe of profiles
        Returns:
        -------
        pandas.DataFrame which includes the sample id column
        """

        _profile = _profile.reset_index(drop=True)
        _feature_df = get_featuredata(_profile)
        _metadata_df = _profile[[self.feature, self.control_type_feature]]
        width = int(np.log10(len(_profile)))+1
        _perturbation_id_df = pd.DataFrame({self.sample_feature: [f'sample_{i:0{width}}' for i in range(len(_metadata_df))]})
        _metadata_df = pd.concat([_metadata_df, _perturbation_id_df], axis=1)
        _profile = pd.concat([_metadata_df, _feature_df], axis=1)
        return _profile

    def compute_correlation(self):
        """
        Compute correlation.
        Returns:
        -------
        pandas.DataFrame of pairwise correlation values.
        """

        _profile1 = get_featuredata(self.profile1)
        _profile2 = get_featuredata(self.profile2)
        _sample_names_1 = list(self.profile1[self.sample_feature])
        _sample_names_2 = list(self.profile2[self.sample_feature])
        _corr = np.corrcoef(_profile1, _profile2)
        _corr = _corr[0:len(_sample_names_1), len(_sample_names_1):]
        if self.anti_correlation:
            _corr = np.abs(_corr)
        if self.within:
            np.fill_diagonal(_corr, 0)
        _corr_df = pd.DataFrame(_corr, columns=_sample_names_2, index=_sample_names_1)
        if self.rank:
            _corr_df = _corr_df.rank(1, method="first")
        _corr_df = self.process_negcon(_corr_df)
        return _corr_df

    def create_truth_matrix(self):
        """
        Compute truth matrix.
        Returns:
        -------
        pandas.DataFrame of binary truth values.
        """

        _truth_matrix = self.corr.unstack().reset_index()
        _truth_matrix = _truth_matrix.merge(self.map2, left_on='level_0', right_on=self.sample_feature, how='left').drop([self.sample_feature,0], axis=1)
        _truth_matrix = _truth_matrix.merge(self.map1, left_on='level_1', right_on=self.sample_feature, how='left').drop([self.sample_feature], axis=1)
        _truth_matrix['value'] = np.where(_truth_matrix[f'{self.feature}_x'] == _truth_matrix[f'{self.feature}_y'], 1, 0)
        if self.within:
            _truth_matrix['value'] = np.where(_truth_matrix['level_0'] == _truth_matrix['level_1'], 0, _truth_matrix['value'])
        _truth_matrix = _truth_matrix.pivot('level_1', 'level_0', 'value').reset_index().set_index('level_1')
        _truth_matrix.index.name = None
        _truth_matrix = _truth_matrix.rename_axis(None, axis=1)
        return _truth_matrix

    def calculate_average_precision_per_sample(self):
        """
        Compute average precision score per sample.
        Returns:
        -------
        pandas.DataFrame of average precision values.
        """

        _score = []
        for _sample in self.corr.index:
            _y_true, _y_pred = self.filter_nan(self.truth_matrix.loc[_sample].values, self.corr.loc[_sample].values)
            _score.append(average_precision_score(_y_true, _y_pred))

        _ap_sample_df = self.map1.copy()
        _ap_sample_df['ap'] = _score
        if self.challenge_negcon:
            _ap_sample_df = _ap_sample_df.query(f'{self.control_type_feature}!="negcon"').drop(columns=[self.control_type_feature]).reset_index(drop=True)
        else:
            _ap_sample_df = _ap_sample_df.drop(columns=[self.control_type_feature]).reset_index(drop=True)
        return _ap_sample_df

    def calculate_average_precision_at_k_per_sample(self):
        """
        Compute average precision at k per sample.
        Returns:
        -------
        pandas.DataFrame of average precision at k values.
        """

        _score = []
        for _sample in self.corr.index:
            _y_true, _y_pred = self.filter_nan(self.truth_matrix.loc[_sample].values, self.corr.loc[_sample].values)
            _score.append(self.precision_at_k(_y_true, _y_pred, self.k))

        _pk_sample_df = self.map1.copy()
        _pk_sample_df['p_k'] = _score
        if self.challenge_negcon:
            _pk_sample_df = _pk_sample_df.query(f'{self.control_type_feature}!="negcon"').drop(columns=[self.control_type_feature]).reset_index(drop=True)
        else:
            _pk_sample_df = _pk_sample_df.drop(columns=[self.control_type_feature]).reset_index(drop=True)
        return _pk_sample_df

    def calculate_average_precision_at_r_per_sample(self):
        """
        Compute average precision at r per sample.
        Returns:
        -------
        pandas.DataFrame of average precision at r values.
        """

        _score = []
        for _sample in self.corr.index:
            _y_true, _y_pred = self.filter_nan(self.truth_matrix.loc[_sample].values, self.corr.loc[_sample].values)
            _r = int(np.sum(_y_true))
            _score.append(self.precision_at_k(_y_true, _y_pred, _r))

        _pr_sample_df = self.map1.copy()
        _pr_sample_df['p_r'] = _score
        if self.challenge_negcon:
            _pr_sample_df = _pr_sample_df.query(f'{self.control_type_feature}!="negcon"').drop(columns=[self.control_type_feature]).reset_index(drop=True)
        else:
            _pr_sample_df = _pr_sample_df.drop(columns=[self.control_type_feature]).reset_index(drop=True)
        return _pr_sample_df

    def calculate_average_precision_score_per_group(self, precision_score):
        """
        Compute average precision score per sample group.
        Returns:
        -------
        pandas.DataFrame of average precision values.
        """

        _precision_group_df = precision_score.groupby(self.feature).apply(lambda x: np.mean(x)).reset_index()
        return _precision_group_df

    @staticmethod
    def calculate_mean_average_precision_score(precision_score):
        """
        Compute mean average precision score.
        Returns:
        -------
        mean average precision score.
        """

        return precision_score.mean().values[0]

    @staticmethod
    def precision_at_k(_true, _pred, _k):
        """
        Calculate precision at k
        Parameters:
        -----------
        _true: list or array
            list of truth labels
        _pred: list or array
            list of predictions
        _k: int
            value at which precision is computed.
        Returns:
        -------
        precision at k
        """

        _arg_sort_pred = list(tuple(np.argsort(_pred)[::-1]))
        _sorted_pred_k = np.asarray(_pred)[_arg_sort_pred][:_k]
        _sorted_true_k = np.asarray(_true)[_arg_sort_pred][:_k]

        _precision_k = np.sum(_sorted_true_k) / _k
        return _precision_k

    def process_negcon(self, _corr_df):
        """
        Keep or remove negcon
        Parameters:
        -----------
        _corr_df: pandas.DataFrame
            pairwise correlation dataframe
        Returns:
        -------
        pandas.DataFrame of pairwise correlation values
        """
        _corr_df = _corr_df.unstack().reset_index()
        _corr_df['filter'] = 1
        _corr_df = _corr_df.merge(self.map2, left_on='level_0', right_on=self.sample_feature, how='left').drop([self.sample_feature], axis=1)
        _corr_df = _corr_df.merge(self.map1, left_on='level_1', right_on=self.sample_feature, how='left').drop([self.sample_feature], axis=1)

        if self.challenge_negcon:
            _corr_df['filter'] = np.where(_corr_df[f'{self.feature}_x'] != _corr_df[f'{self.feature}_y'], 0, _corr_df['filter'])
            _corr_df['filter'] = np.where(_corr_df[f'{self.control_type_feature}_x'] == "negcon", 1, _corr_df['filter'])
            _corr_df['filter'] = np.where(_corr_df[f'{self.control_type_feature}_y'] == "negcon", 0, _corr_df['filter'])
        else:
            _corr_df['filter'] = np.where(_corr_df[f'{self.control_type_feature}_x'] == "negcon", 0, _corr_df['filter'])
            _corr_df['filter'] = np.where(_corr_df[f'{self.control_type_feature}_y'] == "negcon", 0, _corr_df['filter'])

        _corr_df = _corr_df.query('filter==1').reset_index(drop=True)

        self.map1 = (
            _corr_df[['level_1', f'{self.feature}_y', f'{self.control_type_feature}_y']].copy()
            .rename(columns={'level_1': self.sample_feature, f'{self.feature}_y': self.feature, f'{self.control_type_feature}_y':self.control_type_feature})
            .drop_duplicates()
            .sort_values(by=self.sample_feature)
            .reset_index(drop=True)
        )
        self.map2 = (
            _corr_df[['level_0', f'{self.feature}_x', f'{self.control_type_feature}_x']].copy()
            .rename(columns={'level_0': self.sample_feature, f'{self.feature}_x': self.feature, f'{self.control_type_feature}_y':self.control_type_feature})
            .drop_duplicates()
            .sort_values(by=self.sample_feature)
            .reset_index(drop=True)
        )

        _corr_df = _corr_df.pivot('level_1', 'level_0', 0).reset_index().set_index('level_1')
        _corr_df.index.name = None
        _corr_df = _corr_df.rename_axis(None, axis=1)
        return _corr_df

    @staticmethod
    def filter_nan(_y_true, _y_pred):
        arg = np.argwhere(~np.isnan(_y_pred))
        return _y_true[arg].flatten(), _y_pred[arg].flatten()


def shuffle_profiles(profiles):
    """
    Shuffle profiles - both rows and columns.
    Parameters:
    -----------
    profiles: pandas.DataFrame
        dataframe of profiles
    Returns:
    -------
    pandas.DataFrame of shuffled profiles.
    """

    feature_cols = get_featurecols(profiles)
    metadata_df = get_metadata(profiles)
    feature_df = get_featuredata(profiles)

    feature_df = feature_df.sample(frac=1).reset_index(drop=True)
    feature_df.columns = feature_cols
    profiles = pd.concat([metadata_df, feature_df], axis=1)
    return profiles


def precision_at_r_threshold(precision_df, shuffled_precision_df):
    """
    Calculate precision@r at various thresholds
    Parameters:
    -----------
    precision_df: pandas.DataFrame
        dataframe of precision values
    shuffled_precision_df: pandas.DataFrame
        dataframe of precision values  for the shuffled profiles
    Returns:
    -------
    pandas.DataFrame of precision@r values at different thresholds.
    """

    precision_values = precision_df.p_r.values
    shuffled_precision_values = shuffled_precision_df.p_r.values
    corrected_values = precision_values - shuffled_precision_values.mean()

    threshold_values = [_/10 for _ in range(1, 10)]

    df = pd.DataFrame()

    for threshold_value in threshold_values:
        percent_perturbations = (corrected_values > threshold_value).sum()/len(corrected_values)
        df = df.append({'threshold': threshold_value,
                        'percent_perturbations': percent_perturbations}, ignore_index=True)

    return df

